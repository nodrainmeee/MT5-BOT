"""
mt5_connector.py : tout ce qui parle au terminal MetaTrader 5.

Règles importantes (cahier des charges §3) :
- la bibliothèque MetaTrader5 n'est importée qu'au moment de la connexion
  (clic sur « Démarrer »). Jamais au lancement, jamais pendant la
  compilation sur GitHub (qui n'a pas MT5) ;
- elle ne fonctionne que sous Windows, avec MT5 Desktop ouvert ;
- toutes les fonctions attrapent les erreurs et renvoient un message clair
  au lieu de planter.

LIMITE TECHNIQUE : la bibliothèque MetaTrader5 n'est pas garantie
"thread-safe". Toutes les fonctions de cette classe passent donc par un
verrou (self._lock) pour qu'un seul appel à la fois parle au terminal.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import pandas as pd

# Codes de MT5 recopiés ici pour ne pas dépendre de constantes qui
# pourraient manquer selon la version de la bibliothèque.
SYMBOL_FILLING_FOK = 1        # drapeau "Fill or Kill" autorisé
SYMBOL_FILLING_IOC = 2        # drapeau "Immediate or Cancel" autorisé
SYMBOL_TRADE_MODE_DISABLED = 0
ACCOUNT_TRADE_MODE = {0: "demo", 1: "contest", 2: "real"}
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3
DEAL_REASON = {3: "fermeture par le bot", 4: "stop loss atteint", 5: "take profit atteint",
               6: "stop out (marge insuffisante)", 0: "fermeture manuelle (terminal)",
               1: "fermeture manuelle (mobile)", 2: "fermeture manuelle (web)"}

# Messages clairs pour les codes de retour d'ordre les plus courants
RETCODES = {
    10004: "Requote (prix changé), nouvel essai à la prochaine bougie",
    10006: "Ordre rejeté par le serveur",
    10013: "Requête invalide",
    10014: "Volume invalide",
    10015: "Prix invalide",
    10016: "Stops invalides (SL/TP trop proches ?)",
    10017: "Trading désactivé sur ce compte",
    10018: "Marché fermé",
    10019: "Fonds insuffisants",
    10024: "Trop de requêtes",
    10027: "Algo Trading désactivé dans MT5 (bouton « Algo Trading » de la barre d'outils)",
    10030: "Mode de remplissage non supporté par le symbole",
    10031: "Pas de connexion au serveur du broker",
}


class MT5Error(Exception):
    """Erreur de communication avec MetaTrader 5."""


class MT5Connector:
    def __init__(self, journal):
        self.journal = journal
        self.mt5 = None                  # module MetaTrader5, importé plus tard
        self._lock = threading.RLock()
        self._creds: dict = {}           # identifiants de la session (en mémoire seulement)
        self._symbol_cache: dict = {}    # "EURUSD" -> "EURUSDm" (par exemple)
        self.initialized = False

    # ================================================================ connexion
    def _import(self):
        if self.mt5 is None:
            try:
                import MetaTrader5 as mt5   # import tardif, volontaire
            except ImportError as exc:
                raise MT5Error("Bibliothèque MetaTrader5 introuvable. Elle ne fonctionne "
                               "que sous Windows.") from exc
            self.mt5 = mt5
        return self.mt5

    def connect(self, login: str = "", password: str = "", server: str = "",
                path: str = "") -> tuple[bool, str]:
        """Se connecte au terminal MT5 ouvert.

        - Si login/mot de passe/serveur sont vides : on se branche sur le
          compte DÉJÀ connecté dans le terminal MT5 (le plus simple).
        - Sinon on demande à MT5 de se connecter à ce compte.
        """
        with self._lock:
            try:
                mt5 = self._import()
            except MT5Error as exc:
                return False, str(exc)
            self._creds = {"login": login, "password": password, "server": server, "path": path}
            kwargs = {"timeout": 60_000}
            if login:
                kwargs.update(login=int(login), password=password or "", server=server or "")
            try:
                ok = mt5.initialize(path, **kwargs) if path else mt5.initialize(**kwargs)
            except Exception as exc:  # erreur inattendue de la bibliothèque
                return False, f"Erreur MT5 inattendue : {exc}"
            if not ok:
                code, msg = mt5.last_error()
                self.initialized = False
                return False, (f"Connexion à MT5 impossible ({code} : {msg}). Vérifiez que "
                               "MetaTrader 5 est ouvert, connecté à votre compte, et lancé "
                               "avec les mêmes droits que MonBot.")
            self.initialized = True
            self._symbol_cache.clear()
            ai = mt5.account_info()
            if ai is None:
                return False, "MT5 est ouvert mais aucun compte n'est connecté."
            return True, f"Connecté au compte {ai.login} ({ai.server})"

    def ensure_connected(self, stop_event: threading.Event | None = None,
                         essais: int = 3) -> bool:
        """Vérifie la connexion et se reconnecte automatiquement si besoin."""
        with self._lock:
            if self.mt5 is None:
                return False
            ti = self.mt5.terminal_info()
            if ti is not None and ti.connected and self.mt5.account_info() is not None:
                return True
        for n in range(1, essais + 1):
            if stop_event is not None and stop_event.is_set():
                return False
            self.journal.warning(f"Connexion MT5 perdue, tentative de reconnexion {n}/{essais}...")
            with self._lock:
                try:
                    self.mt5.shutdown()
                except Exception:
                    pass
            ok, msg = self.connect(**self._creds)
            if ok:
                self.journal.success("Reconnecté à MT5")
                return True
            # Attente de 5 s, interrompue immédiatement si on arrête le bot
            if stop_event is not None:
                if stop_event.wait(5):
                    return False
            else:
                time.sleep(5)
        self.journal.error("Reconnexion à MT5 impossible. Vérifiez le terminal et Internet.")
        return False

    def shutdown(self):
        with self._lock:
            if self.mt5 is not None and self.initialized:
                try:
                    self.mt5.shutdown()
                except Exception:
                    pass
            self.initialized = False

    # ================================================================ état
    def status(self) -> dict:
        """Témoins d'état : connexion, Algo Trading, type de compte, chiffres."""
        etat = {"connected": False, "algo_trading": False, "account_mode": None,
                "login": None, "server": None, "balance": None, "equity": None,
                "currency": "", "company": ""}
        with self._lock:
            if self.mt5 is None or not self.initialized:
                return etat
            ti = self.mt5.terminal_info()
            ai = self.mt5.account_info()
            if ti is None or ai is None:
                return etat
            etat.update(
                connected=bool(ti.connected),
                # Les 2 conditions : bouton "Algo Trading" du terminal ET droit du compte
                algo_trading=bool(ti.trade_allowed) and bool(ai.trade_expert),
                account_mode=ACCOUNT_TRADE_MODE.get(ai.trade_mode, "inconnu"),
                login=ai.login, server=ai.server, balance=float(ai.balance),
                equity=float(ai.equity), currency=ai.currency, company=ai.company)
        return etat

    # ================================================================ symboles
    def resolve_symbol(self, base: str) -> str | None:
        """Trouve le vrai nom du symbole chez le broker.

        Exness ajoute souvent un suffixe : "EURUSDm" (Standard), "EURUSDc"
        (Cent), etc. On cherche les symboles qui commencent par le nom de
        base, on garde ceux qui sont tradables, et on les affiche dans le
        "Market Watch" de MT5 (obligatoire pour recevoir les prix).
        """
        base = base.upper()
        if base in self._symbol_cache:
            return self._symbol_cache[base]
        with self._lock:
            tous = self.mt5.symbols_get() or ()
            candidats = []
            for s in tous:
                nom = s.name
                if nom.upper().startswith(base) and len(nom) <= len(base) + 4:
                    if getattr(s, "trade_mode", 4) != SYMBOL_TRADE_MODE_DISABLED:
                        candidats.append(nom)
            if not candidats:
                return None
            # Priorité : nom exact, puis le plus court, puis ordre alphabétique
            candidats.sort(key=lambda n: (n.upper() != base, len(n), n))
            choisi = candidats[0]
            if not self.mt5.symbol_select(choisi, True):
                return None
            self._symbol_cache[base] = choisi
            return choisi

    def symbol_info(self, nom: str):
        with self._lock:
            return self.mt5.symbol_info(nom)

    def tick(self, nom: str):
        with self._lock:
            return self.mt5.symbol_info_tick(nom)

    # ================================================================ données
    def get_closed_rates(self, nom: str, timeframe: str, nombre: int = 1000) -> pd.DataFrame | None:
        """Renvoie les 'nombre' dernières bougies CLÔTURÉES (sans la bougie en cours)."""
        with self._lock:
            tf = {"M1": self.mt5.TIMEFRAME_M1, "M5": self.mt5.TIMEFRAME_M5}[timeframe]
            rates = self.mt5.copy_rates_from_pos(nom, tf, 0, nombre + 1)
        if rates is None or len(rates) < 3:
            return None
        df = pd.DataFrame(rates)
        # MT5 donne l'heure en secondes ; on la convertit (heure du serveur)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.iloc[:-1].reset_index(drop=True)   # on retire la bougie en formation

    # ================================================================ calculs
    def loss_per_lot(self, nom: str, direction: str, entree: float, sl: float) -> float:
        """Argent perdu (devise du compte) si 1 lot va de 'entree' au stop loss.

        On demande à MT5 lui-même (order_calc_profit) : c'est la méthode la
        plus fiable, valable pour le Forex, l'or, les comptes Cent, etc.
        """
        with self._lock:
            typ = self.mt5.ORDER_TYPE_BUY if direction == "BUY" else self.mt5.ORDER_TYPE_SELL
            p = self.mt5.order_calc_profit(typ, nom, 1.0, entree, sl)
            if p is not None:
                return abs(float(p))
            # Solution de secours : valeur d'un "tick" fournie par le symbole
            info = self.mt5.symbol_info(nom)
            if info is None or info.trade_tick_size <= 0:
                return 0.0
            return abs(entree - sl) / info.trade_tick_size * info.trade_tick_value

    def _filling(self, info) -> int:
        """Choisit le mode de remplissage accepté par le symbole (Exness : souvent FOK/IOC)."""
        mode = int(getattr(info, "filling_mode", 0))
        if mode & SYMBOL_FILLING_FOK:
            return self.mt5.ORDER_FILLING_FOK
        if mode & SYMBOL_FILLING_IOC:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    # ================================================================ ordres
    def send_market_order(self, nom: str, direction: str, volume: float,
                          sl_dist: float, tp_dist: float, magic: int,
                          commentaire: str = "MonBot") -> tuple[bool, str, dict]:
        """Envoie un ordre au marché AVEC stop loss et take profit dès l'ouverture."""
        with self._lock:
            mt5 = self.mt5
            info = mt5.symbol_info(nom)
            t = mt5.symbol_info_tick(nom)
            if info is None or t is None:
                return False, "Prix indisponible", {}
            if direction == "BUY":
                prix, typ = t.ask, mt5.ORDER_TYPE_BUY
                sl, tp = prix - sl_dist, prix + tp_dist
            else:
                prix, typ = t.bid, mt5.ORDER_TYPE_SELL
                sl, tp = prix + sl_dist, prix - tp_dist
            d = info.digits
            requete = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": nom, "volume": float(volume),
                "type": typ, "price": round(prix, d), "sl": round(sl, d), "tp": round(tp, d),
                "deviation": 20, "magic": int(magic), "comment": commentaire[:25],
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(info),
            }
            res = mt5.order_send(requete)
            if res is None:
                code, msg = mt5.last_error()
                return False, f"Ordre non envoyé ({code} : {msg})", requete
            if res.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
                texte = RETCODES.get(res.retcode, res.comment)
                return False, f"Ordre refusé ({res.retcode}) : {texte}", requete
            requete["ticket"] = res.order
            requete["price"] = res.price or requete["price"]
            requete["volume"] = res.volume or requete["volume"]
            return True, "Ordre exécuté", requete

    def positions(self, magic: int) -> list:
        """Positions ouvertes PAR LE BOT uniquement (filtre sur le magic number)."""
        with self._lock:
            toutes = self.mt5.positions_get() or ()
        return [p for p in toutes if p.magic == magic]

    def close_position(self, pos, magic: int) -> tuple[bool, str]:
        with self._lock:
            mt5 = self.mt5
            info = mt5.symbol_info(pos.symbol)
            t = mt5.symbol_info_tick(pos.symbol)
            if info is None or t is None:
                return False, "Prix indisponible"
            if pos.type == mt5.POSITION_TYPE_BUY:
                typ, prix = mt5.ORDER_TYPE_SELL, t.bid
            else:
                typ, prix = mt5.ORDER_TYPE_BUY, t.ask
            requete = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
                "type": typ, "position": pos.ticket, "price": prix, "deviation": 30,
                "magic": magic, "comment": "MonBot fermeture",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(info),
            }
            res = mt5.order_send(requete)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                code = res.retcode if res is not None else mt5.last_error()
                return False, f"Fermeture refusée ({code})"
            return True, "Position fermée"

    # ================================================================ historique
    def deals_between(self, debut: datetime, fin: datetime, magic: int) -> list:
        """Transactions (deals) du bot entre deux dates."""
        with self._lock:
            deals = self.mt5.history_deals_get(debut, fin) or ()
        return [d for d in deals if d.magic == magic]

    def closing_info(self, ticket_position: int) -> dict | None:
        """Résultat d'une position fermée : prix, profit total, raison (TP/SL...)."""
        with self._lock:
            deals = self.mt5.history_deals_get(position=ticket_position) or ()
        sorties = [d for d in deals if d.entry in (DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY)]
        if not sorties:
            return None
        profit = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals)
        dernier = sorties[-1]
        return {"price": dernier.price, "profit": profit,
                "reason": DEAL_REASON.get(dernier.reason, f"raison {dernier.reason}")}
