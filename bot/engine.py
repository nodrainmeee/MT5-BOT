"""
engine.py : le "moteur" du bot. Il tourne dans un THREAD SÉPARÉ pour que
l'interface ne se fige jamais (cahier des charges §2).

Boucle principale (toutes les 3 secondes) :
 1. vérifier la connexion MT5 (reconnexion automatique) ;
 2. lire solde, équité, positions et transactions du jour ;
 3. détecter les positions fermées (TP/SL atteint) et lancer la pause
    après une perte ;
 4. vérifier la perte maximale du jour (arrêt automatique) ;
 5. pour chaque actif coché, dès qu'une NOUVELLE bougie est clôturée :
    stratégie -> filtres (horaire, spread, risque) -> taille du lot -> ordre.
"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from .config import MAGIC_NUMBER, ConfigStore
from .mt5_connector import DEAL_ENTRY_IN, MT5Connector
from .risk import LotResult, RiskManager, compute_fixed_money, compute_lot
from .strategy import (StrategyParams, adjust_distances, evaluate, in_session,
                       spread_is_abnormal)

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")   # nécessite le paquet "tzdata" sous Windows
except Exception:                      # secours : heure locale du PC
    PARIS = None

INTERVALLE_BOUCLE = 3.0      # secondes entre deux vérifications
NB_BOUGIES = 1000            # historique chargé (EMA 200 fiable)


def maintenant_paris() -> datetime:
    return datetime.now(PARIS) if PARIS else datetime.now().astimezone()


class TradingEngine:
    def __init__(self, store: ConfigStore, journal):
        self.store = store
        self.journal = journal
        self.connector = MT5Connector(journal)
        self.risk = RiskManager()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._last_bar: dict = {}          # symbole -> heure de la dernière bougie analysée
        self._known_positions: dict = {}   # ticket -> infos (pour détecter les fermetures)
        self._warned: set = set()          # avertissements déjà affichés (anti-répétition)
        self._symbols: dict = {}           # "EURUSD" -> "EURUSDm"
        self._pnl_curve: list = []         # [[horodatage, résultat du jour], ...]
        self._state = self._etat_initial()

    # ================================================================ état partagé
    @staticmethod
    def _etat_initial() -> dict:
        return {"running": False, "starting": False, "connected": False,
                "algo_trading": False, "account_mode": None, "login": None,
                "server": None, "balance": None, "equity": None, "currency": "",
                "daily_pnl": 0.0, "daily_pnl_pct": 0.0, "trades_today": 0,
                "open_positions": 0, "pause_message": "", "halt_message": "",
                "symbols_resolved": {}}

    def _set(self, **kw):
        with self._state_lock:
            self._state.update(kw)

    def snapshot(self) -> dict:
        """Copie de l'état pour l'interface (appelée chaque seconde)."""
        # Bot arrêté mais MT5 encore branché : on rafraîchit les témoins quand même
        if not self.is_running() and self.connector.initialized:
            try:
                self._set(**{k: v for k, v in self.connector.status().items()
                             if k in self._state})
            except Exception:
                pass
        with self._state_lock:
            etat = dict(self._state)
            etat["pnl_curve"] = list(self._pnl_curve[-600:])
        return etat

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ================================================================ commandes
    def start(self, login: str, password: str, server: str, path: str = "") -> tuple[bool, str]:
        if self.is_running():
            return False, "Le bot tourne déjà"
        self._stop.clear()
        self._set(starting=True, halt_message="")
        self._thread = threading.Thread(target=self._run, args=(login, password, server, path),
                                        name="MonBot-moteur", daemon=True)
        self._thread.start()
        return True, "Démarrage en cours..."

    def stop(self, raison: str = "Arrêt demandé par l'utilisateur", attendre: bool = True):
        if not self.is_running():
            self._set(running=False, starting=False)
            return
        self._stop.set()
        self.journal.info(f"Arrêt du bot : {raison}")
        if attendre and self._thread is not threading.current_thread():
            self._thread.join(timeout=15)
        self._set(running=False, starting=False)

    def open_positions_count(self) -> int:
        if not self.connector.initialized:
            return 0
        try:
            return len(self.connector.positions(MAGIC_NUMBER))
        except Exception:
            return 0

    def close_all_positions(self) -> dict:
        """Ferme toutes les positions ouvertes PAR LE BOT (magic number)."""
        if self.is_running():
            self.stop("fermeture des positions demandée")
        fermees, echecs = 0, 0
        if not self.connector.initialized:
            return {"closed": 0, "failed": 0, "message": "MT5 n'est pas connecté"}
        for pos in self.connector.positions(MAGIC_NUMBER):
            ok, msg = self.connector.close_position(pos, MAGIC_NUMBER)
            if ok:
                fermees += 1
                self.journal.warning(f"Position {pos.symbol} #{pos.ticket} fermée (arrêt d'urgence)")
            else:
                echecs += 1
                self.journal.error(f"Échec fermeture {pos.symbol} #{pos.ticket} : {msg}")
        return {"closed": fermees, "failed": echecs,
                "message": f"{fermees} position(s) fermée(s), {echecs} échec(s)"}

    def pause_news(self, minutes: int):
        self.risk.set_pause(maintenant_paris(), minutes, "pause annonces économiques")
        self.journal.warning(f"Pause manuelle « annonces » : aucun nouvel ordre pendant {minutes} min")

    def resume(self):
        if not self.risk.halted:
            self.risk.clear_pause()
            self.journal.info("Pause levée")

    def shutdown(self):
        """Appelé à la fermeture de la fenêtre."""
        self.stop("fermeture du logiciel")
        self.connector.shutdown()

    # ================================================================ thread
    def _run(self, login, password, server, path):
        try:
            if not self._startup_checks(login, password, server, path):
                return
            self._set(running=True, starting=False)
            self.journal.success("Bot démarré. Analyse à chaque nouvelle bougie clôturée.")
            while not self._stop.is_set():
                debut = time.monotonic()
                try:
                    self._cycle()
                except Exception as exc:
                    # Aucune erreur silencieuse : on écrit tout dans le journal
                    self.journal.error(f"Erreur pendant le cycle : {exc}")
                    self.journal.log(traceback.format_exc(limit=3), "error")
                    self._stop.wait(10)
                if self.risk.halted:
                    self.journal.error(f"{self.risk.halt_reason}. Le bot s'arrête pour aujourd'hui. "
                                       "Les positions déjà ouvertes gardent leur stop loss.")
                    self._set(halt_message=self.risk.halt_reason)
                    break
                reste = INTERVALLE_BOUCLE - (time.monotonic() - debut)
                self._stop.wait(max(0.2, reste))
        except Exception as exc:
            self.journal.error(f"Erreur grave, bot arrêté : {exc}")
            self.journal.log(traceback.format_exc(limit=5), "error")
        finally:
            self._set(running=False, starting=False)
            self.journal.info("Bot à l'arrêt.")

    def _startup_checks(self, login, password, server, path) -> bool:
        s = self.store.get()
        self.journal.info("Connexion à MetaTrader 5...")
        ok, msg = self.connector.connect(login, password, server, path)
        if not ok:
            self.journal.error(msg)
            return False
        self.journal.success(msg)
        st = self.connector.status()
        self._set(**{k: v for k, v in st.items() if k in self._state})

        # 1. Connexion au serveur du broker
        if not st["connected"]:
            self.journal.error("MT5 n'est pas connecté au serveur du broker (vérifiez Internet).")
            return False
        # 2. Algo Trading
        if not st["algo_trading"]:
            self.journal.error("Algo Trading est DÉSACTIVÉ dans MT5 : cliquez sur le bouton "
                               "« Algo Trading » de la barre d'outils de MT5, puis redémarrez le bot.")
            return False
        # 3. Démo ou réel
        mode = st["account_mode"]
        libelle = {"demo": "DÉMO", "real": "RÉEL", "contest": "CONCOURS"}.get(mode, str(mode))
        self.journal.info(f"Type de compte : {libelle} ({st['currency']})")
        if mode == "real" and not s.real_mode_enabled:
            self.journal.error("Compte RÉEL détecté alors que le mode réel n'est pas activé. "
                               "Par sécurité, le bot refuse de démarrer. Activez le mode réel "
                               "dans l'interface (confirmation obligatoire) ou connectez un compte démo.")
            return False
        if mode == "real":
            self.journal.warning("ATTENTION : vous tradez avec de l'argent réel.")
        if str(st["currency"]).upper() in ("USC", "EUC"):
            self.journal.info("Compte Cent détecté : les montants sont affichés en cents.")
        # 4. Symboles (suffixes Exness)
        actifs = [b for b, on in s.symbols.items() if on]
        if not actifs:
            self.journal.error("Aucun actif coché.")
            return False
        self._symbols = {}
        for base in actifs:
            nom = self.connector.resolve_symbol(base)
            if nom is None:
                self.journal.warning(f"{base} introuvable chez ce broker : ignoré.")
                continue
            self._symbols[base] = nom
            self.journal.info(f"{base} -> symbole « {nom} » trouvé")
            if base == "XAUUSD":
                self.journal.warning("XAUUSD (or) est très volatil : petit capital = compte Cent recommandé.")
        if not self._symbols:
            self.journal.error("Aucun symbole utilisable.")
            return False
        self._set(symbols_resolved=dict(self._symbols))

        # Positions déjà ouvertes par le bot (redémarrage) : on les suit
        self._known_positions = {p.ticket: self._pos_info(p)
                                 for p in self.connector.positions(MAGIC_NUMBER)}
        if self._known_positions:
            self.journal.info(f"{len(self._known_positions)} position(s) du bot déjà ouverte(s), suivies.")
        self._last_bar = {}
        self.journal.info(f"Plage horaire : {s.session_start}-{s.session_end} (heure de Paris), "
                          f"unité de temps {s.timeframe}.")
        return True

    @staticmethod
    def _pos_info(p) -> dict:
        return {"symbol": p.symbol, "volume": p.volume,
                "direction": "BUY" if p.type == 0 else "SELL", "price": p.price_open}

    # ================================================================ un cycle
    def _cycle(self):
        s = self.store.get()   # relu à chaque cycle : les réglages s'appliquent en direct
        if not self.connector.ensure_connected(self._stop):
            self._set(connected=False)
            return
        st = self.connector.status()
        self._set(**{k: v for k, v in st.items() if k in self._state})
        now = maintenant_paris()

        # ---- Chiffres du jour à partir de l'historique MT5 (fiable même après redémarrage)
        debut_jour = now.replace(hour=0, minute=0, second=0, microsecond=0)
        debut_utc = debut_jour.astimezone(timezone.utc)
        fin_utc = datetime.now(timezone.utc) + timedelta(days=1)
        deals = self.connector.deals_between(debut_utc, fin_utc, MAGIC_NUMBER)
        realise = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals)
        nb_trades = sum(1 for d in deals if d.entry == DEAL_ENTRY_IN)
        if self.risk.sync(now.date(), st["balance"] or 0.0, realise, nb_trades):
            self._pnl_curve = []
            self._warned.discard("pause")

        # ---- Positions et détection des fermetures (TP/SL)
        positions = self.connector.positions(MAGIC_NUMBER)
        tickets = {p.ticket for p in positions}
        for ticket in list(self._known_positions):
            if ticket not in tickets:
                self._on_position_closed(ticket, self._known_positions.pop(ticket), s, now)
        for p in positions:
            self._known_positions.setdefault(p.ticket, self._pos_info(p))
        flottant = sum(p.profit + p.swap for p in positions)

        pnl = self.risk.daily_pnl(flottant)
        pct = self.risk.daily_pnl_pct(flottant)
        ts = int(time.time())
        if not self._pnl_curve or ts - self._pnl_curve[-1][0] >= 15:
            self._pnl_curve.append([ts, round(pnl, 2)])
        pause = ""
        if self.risk.is_paused(now):
            pause = f"En pause jusqu'à {self.risk.pause_until:%H:%M} ({self.risk.pause_reason})"
        self._set(daily_pnl=round(pnl, 2), daily_pnl_pct=round(pct, 2),
                  trades_today=self.risk.trades_today, open_positions=len(positions),
                  pause_message=pause)

        # ---- Perte maximale du jour : NON désactivable
        if self.risk.check_daily_loss(flottant, s.daily_loss_max):
            return

        if not st["algo_trading"]:
            self._warn_once("algo", "Algo Trading désactivé dans MT5 : aucun ordre possible.")
            return
        self._warned.discard("algo")

        # ---- Analyse de chaque actif coché
        par_symbole = {}
        for p in positions:
            par_symbole[p.symbol] = par_symbole.get(p.symbol, 0) + 1
        for base, on in s.symbols.items():
            if not on or self._stop.is_set():
                continue
            nom = self._symbols.get(base) or self.connector.resolve_symbol(base)
            if not nom:
                self._warn_once(f"sym-{base}", f"{base} introuvable chez ce broker.")
                continue
            self._symbols[base] = nom
            if self._process_symbol(base, nom, s, now, par_symbole, len(positions)):
                par_symbole[nom] = par_symbole.get(nom, 0) + 1
                positions = positions + [None]   # compte la nouvelle position

    def _warn_once(self, cle: str, message: str):
        if cle not in self._warned:
            self._warned.add(cle)
            self.journal.warning(message)

    def _on_position_closed(self, ticket, info, s, now):
        res = self.connector.closing_info(ticket)
        if res is None:
            self.journal.info(f"Position {info['symbol']} #{ticket} fermée (détails indisponibles)")
            return
        profit = res["profit"]
        niveau = "success" if profit >= 0 else "warning"
        self.journal.log(f"{info['symbol']} #{ticket} : {res['reason']}, résultat "
                         f"{profit:+.2f}", niveau)
        self.journal.record_trade_close(ticket, res["price"], profit, res["reason"])
        if profit < 0 and s.pause_after_loss_min > 0:
            self.risk.register_loss(now, s.pause_after_loss_min)
            self.journal.info(f"Pause de {s.pause_after_loss_min} min après ce trade perdant.")

    # ================================================================ un symbole
    def _process_symbol(self, base, nom, s, now, par_symbole, total_positions) -> bool:
        """Analyse un symbole. Renvoie True si un ordre a été ouvert."""
        rates = self.connector.get_closed_rates(nom, s.timeframe, NB_BOUGIES)
        if rates is None:
            self._warn_once(f"rates-{nom}", f"{nom} : historique indisponible pour le moment.")
            return False
        derniere = rates["time"].iloc[-1]
        if self._last_bar.get(nom) == derniere:
            return False                    # bougie déjà analysée : on attend la suivante
        premiere_fois = nom not in self._last_bar
        self._last_bar[nom] = derniere
        if premiere_fois:
            # Au démarrage, on n'entre pas sur une bougie déjà clôturée depuis longtemps
            return False

        params = StrategyParams.from_settings(s)
        d = evaluate(rates, params)
        if d.action is None:
            if d.is_filtered:
                self.journal.info(f"{nom} : {d.reason}")
            return False
        self.journal.signal(f"{nom} : {d.reason}")

        # ---- Filtre horaire
        if not in_session(now, s.session_start, s.session_end):
            self.journal.info(f"{nom} : signal ignoré, hors plage horaire "
                              f"({s.session_start}-{s.session_end}, lun-ven)")
            return False

        # ---- Filtre de spread
        info = self.connector.symbol_info(nom)
        t = self.connector.tick(nom)
        if info is None or t is None:
            self.journal.warning(f"{nom} : prix indisponible, signal ignoré")
            return False
        point = info.point
        spread_pts = (t.ask - t.bid) / point if point else 0
        anormal, mediane = spread_is_abnormal(spread_pts, rates["spread"].tail(200),
                                              s.spread_factor_max)
        if anormal:
            self.journal.info(f"{nom} : signal ignoré, spread trop élevé ({spread_pts:.0f} pts, "
                              f"normale {mediane:.0f} pts)")
            return False

        # ---- Règles de risque
        ok, raison = self.risk.can_open(nom, now, par_symbole, total_positions,
                                        s.max_trades_per_day, s.max_total_positions)
        if not ok:
            self.journal.info(f"{nom} : signal ignoré, {raison}")
            return False

        # ---- Distances SL/TP (minimum = spread et distance broker)
        stops_level = info.trade_stops_level * point
        sl_dist, tp_dist = adjust_distances(d.sl_distance, d.tp_distance,
                                            t.ask - t.bid, stops_level, s.reward_risk)

        # ---- Taille de position
        entree = t.ask if d.action == "BUY" else t.bid
        sl_prix = entree - sl_dist if d.action == "BUY" else entree + sl_dist
        perte_lot = self.connector.loss_per_lot(nom, d.action, entree, sl_prix)
        # Capital de référence = le plus petit entre solde et équité (prudence)
        solde = float(self._state.get("balance") or 0.0)
        equite = float(self._state.get("equity") or solde)
        capital = min(solde, equite)
        if s.fixed_money_mode:
            # Montants fixes : TP = +fixed_tp_money, SL = -fixed_sl_money (posés chez le broker)
            ok, raison = self.risk.can_risk_amount(float(self._state.get("daily_pnl") or 0.0),
                                                   s.fixed_sl_money, s.daily_loss_max)
            if not ok:
                self.journal.info(f"{nom} : signal ignoré, {raison}")
                return False
            unite = perte_lot / sl_dist if sl_dist > 0 else 0.0
            fx = compute_fixed_money(capital, s.fixed_sl_money, s.fixed_tp_money, unite, sl_dist,
                                     info.volume_min, info.volume_step, info.volume_max,
                                     sl_dist_min=max((t.ask - t.bid) * 3.0, stops_level + (t.ask - t.bid)),
                                     tp_dist_min=stops_level + (t.ask - t.bid))
            if not fx.ok:
                self.journal.warning(f"{nom} : {fx.reason}")
                return False
            sl_dist, tp_dist = fx.sl_dist, fx.tp_dist
            lot = LotResult(True, volume=fx.volume, risk_amount=s.fixed_sl_money,
                            risk_pct=s.fixed_sl_money / capital * 100.0, reason="OK")
        else:
            lot = compute_lot(capital, s.risk_per_trade, perte_lot,
                              info.volume_min, info.volume_step, info.volume_max)
            if not lot.ok:
                self.journal.warning(f"{nom} : {lot.reason}")
                return False

        # ---- Envoi de l'ordre (SL et TP TOUJOURS posés à l'ouverture)
        sens = "ACHAT" if d.action == "BUY" else "VENTE"
        ok, msg, req = self.connector.send_market_order(nom, d.action, lot.volume, sl_dist,
                                                        tp_dist, MAGIC_NUMBER, f"MonBot {d.signal}")
        if not ok:
            self.journal.error(f"{nom} : {sens} refusé. {msg}")
            return False
        self.risk.trades_today += 1
        self.journal.success(
            f"{nom} : {sens} {req['volume']:g} lot à {req['price']} | SL {req['sl']} | "
            f"TP {req['tp']} | risque ≈ {lot.risk_amount:.2f} ({lot.risk_pct:.2f} %)"
            + (f" | gain visé {s.fixed_tp_money:.2f}" if s.fixed_money_mode else ""))
        self.journal.record_trade_open(req.get("ticket", 0), nom, d.action, req["volume"],
                                       req["price"], req["sl"], req["tp"], d.signal)
        return True
