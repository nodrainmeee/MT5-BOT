"""
backtest.py : teste la stratégie de MonBot sur des données historiques.

Il utilise EXACTEMENT la même stratégie (bot/strategy.py) et les mêmes
règles de risque (bot/risk.py) que le bot réel.

Trois façons de l'utiliser (dans un terminal, dossier du projet) :

 1) Avec un fichier CSV exporté depuis MT5 :
      python -m backtest.backtest --csv donnees/EURUSD_M5.csv --symbole EURUSD

 2) Directement depuis MT5 (Windows, MT5 ouvert et connecté) :
      python -m backtest.backtest --mt5 --symbole EURUSD --mois 6 --tf M5

 3) Avec des données ALÉATOIRES (juste pour vérifier que tout marche,
    les résultats n'ont AUCUNE valeur) :
      python -m backtest.backtest --synthetique

Hypothèses et limites (à connaître !) :
- On utilise des bougies (OHLC), pas des ticks : à l'intérieur d'une
  bougie, on ne sait pas si le prix a touché d'abord le SL ou le TP. Le
  backtest suppose le PIRE cas (stop loss d'abord) : résultat prudent.
- Les prix des bougies MT5 sont des prix "bid". Le spread de chaque bougie
  (colonne spread, en points) est ajouté pour les achats.
- Pas de glissement (slippage) simulé : le réel sera un peu moins bon.
- Devise du compte supposée = USD. Pour USDJPY, le gain en JPY est
  converti en USD avec le prix de sortie.
- Heure des bougies = heure du serveur. Exness utilise GMT+0 : réglez
  --decalage-serveur si votre broker est différent.
- Compte Cent (--cent) : hypothèse "1 lot Cent = 0,01 lot standard" et
  capital exprimé en dollars. Vérifiez les spécifications du symbole chez
  Exness avant de vous y fier.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Permet de lancer le fichier directement (python backtest/backtest.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.indicators import add_indicators          # noqa: E402
from bot.risk import compute_fixed_money, compute_lot                    # noqa: E402
from bot.strategy import (StrategyParams, adjust_distances, bars_needed,  # noqa: E402
                          decide_at, in_session, spread_is_abnormal)

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:
    PARIS = timezone(timedelta(hours=1))   # secours approximatif (sans heure d'été)

# Caractéristiques par défaut des symboles (compte standard, en USD)
SPECS = {
    "EURUSD": {"point": 0.00001, "contrat": 100_000, "spread_defaut": 10},
    "GBPUSD": {"point": 0.00001, "contrat": 100_000, "spread_defaut": 14},
    "USDJPY": {"point": 0.001,   "contrat": 100_000, "spread_defaut": 12},
    "XAUUSD": {"point": 0.01,    "contrat": 100,     "spread_defaut": 25},
}


# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
def load_csv(chemin: str) -> pd.DataFrame:
    """Lit un CSV MT5 (onglets, colonnes <DATE> <TIME> <OPEN>...) ou un CSV
    simple (time,open,high,low,close[,spread])."""
    df = pd.read_csv(chemin, sep=None, engine="python")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    if "date" in df.columns and "time" in df.columns:
        brut = df["date"].astype(str) + " " + df["time"].astype(str)
        df["time"] = pd.to_datetime(brut.str.replace(".", "-", regex=False), errors="coerce")
    elif "time" in df.columns:
        if np.issubdtype(df["time"].dtype, np.number):
            df["time"] = pd.to_datetime(df["time"], unit="s")
        else:
            df["time"] = pd.to_datetime(df["time"].astype(str).str.replace(".", "-", regex=False),
                                        errors="coerce")
    else:
        raise ValueError("Colonne de date introuvable (attendu : time, ou date + time)")
    manquantes = {"open", "high", "low", "close"} - set(df.columns)
    if manquantes:
        raise ValueError(f"Colonnes manquantes : {sorted(manquantes)}")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    if "spread" not in df.columns:
        df["spread"] = np.nan
    return df[["time", "open", "high", "low", "close", "spread"]]


def load_mt5(symbole: str, tf: str, mois: int) -> pd.DataFrame:
    """Télécharge l'historique depuis le terminal MT5 (Windows uniquement).

    LIMITE : MT5 ne renvoie pas plus de bougies que le réglage
    « Outils > Options > Graphiques > Barres max. dans le graphique ».
    """
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 indisponible : {mt5.last_error()}")
    try:
        nom = symbole
        if mt5.symbol_info(nom) is None:   # suffixes Exness (m, c...)
            noms = [s.name for s in (mt5.symbols_get() or ()) if s.name.upper().startswith(symbole)]
            if not noms:
                raise RuntimeError(f"Symbole {symbole} introuvable")
            nom = sorted(noms, key=len)[0]
        mt5.symbol_select(nom, True)
        tfc = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5}[tf]
        fin = datetime.now(timezone.utc)
        debut = fin - timedelta(days=30 * mois)
        rates = mt5.copy_rates_range(nom, tfc, debut, fin)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Aucune donnée reçue : {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        print(f"{len(df)} bougies {nom} {tf} téléchargées depuis MT5")
        return df[["time", "open", "high", "low", "close", "spread"]]
    finally:
        mt5.shutdown()


def synthetic(n: int = 40_000, seed: int = 7) -> pd.DataFrame:
    """Données ALÉATOIRES façon EURUSD M5 (marche aléatoire avec tendances)."""
    rng = np.random.default_rng(seed)
    tendance = np.repeat(rng.normal(0, 0.00003, n // 500 + 1), 500)[:n]
    rendements = rng.normal(0, 0.00025, n) + tendance
    close = 1.10 * np.exp(np.cumsum(rendements))
    open_ = np.concatenate([[close[0]], close[:-1]])
    amp = np.abs(rng.normal(0, 0.00025, n)) * close
    high = np.maximum(open_, close) + amp
    low = np.minimum(open_, close) - amp
    temps = pd.date_range("2025-01-06", periods=n, freq="5min")
    df = pd.DataFrame({"time": temps, "open": open_, "high": high, "low": low,
                       "close": close, "spread": rng.integers(6, 16, n).astype(float)})
    return df[df["time"].dt.weekday < 5].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
@dataclass
class Config:
    symbole: str = "EURUSD"
    capital: float = 30.0
    risque_pct: float = 1.0
    perte_jour_max: float = 3.0
    trades_jour_max: int = 6
    pause_perte_min: int = 10
    session_debut: str = "09:00"
    session_fin: str = "18:00"
    spread_facteur: float = 2.0
    commission_lot: float = 0.0     # commission aller-retour par lot (devise du compte)
    decalage_serveur_h: float = 0.0
    cent: bool = False
    fixed_money: bool = False       # mode montants fixes (TP/SL en argent)
    tp_money: float = 0.50
    sl_money: float = 0.70


def _vers_usd(gain_cotation: float, symbole: str, prix: float) -> float:
    """Convertit un gain exprimé dans la devise de cotation en USD."""
    if symbole.startswith("USD") and not symbole.endswith("USD"):
        return gain_cotation / prix    # ex. USDJPY : gain en JPY -> USD
    return gain_cotation               # EURUSD, GBPUSD, XAUUSD : déjà en USD


def run_backtest(df: pd.DataFrame, cfg: Config, params: StrategyParams) -> dict:
    spec = SPECS.get(cfg.symbole, SPECS["EURUSD"])
    point, contrat = spec["point"], spec["contrat"]
    df = df.copy()
    df["spread"] = df["spread"].fillna(spec["spread_defaut"])
    ind = add_indicators(df, params.trend_ema)
    n = len(ind)
    if n < bars_needed(params) + 10:
        raise ValueError(f"Pas assez de données ({n} bougies)")

    # Lots : standard (min 0,01) ou Cent (hypothèse : 0,01 lot Cent = 0,0001 lot standard)
    lot_min, pas_lot = (0.0001, 0.0001) if cfg.cent else (0.01, 0.01)
    lot_max = 200.0

    decalage = timedelta(hours=cfg.decalage_serveur_h)
    heures_paris = [(t - decalage).replace(tzinfo=timezone.utc).astimezone(PARIS)
                    for t in ind["time"].dt.to_pydatetime()]

    solde = cfg.capital
    courbe = [solde]
    trades = []
    position = None
    attente = None            # signal en attente d'exécution à l'ouverture suivante
    jour, solde_debut_jour, trades_jour, arret_jour = None, solde, 0, False
    pause_jusqu_a = None
    ignores = {"horaire": 0, "spread": 0, "risque": 0, "lot_trop_gros": 0}

    for i in range(bars_needed(params), n):
        b = ind.iloc[i]
        maintenant = heures_paris[i]
        spread_prix = b.spread * point

        # --- Nouveau jour : remise à zéro des compteurs
        if maintenant.date() != jour:
            jour, solde_debut_jour, trades_jour, arret_jour = maintenant.date(), solde, 0, False

        # --- 1) Exécution d'un signal de la bougie précédente (à l'ouverture)
        if attente is not None and position is None:
            d = attente
            attente = None
            entree = b.open + spread_prix if d.action == "BUY" else b.open
            sl_d, tp_d = adjust_distances(d.sl_distance, d.tp_distance, spread_prix, 0.0,
                                          params.reward_risk)
            perte_lot = _vers_usd(sl_d * contrat, cfg.symbole, b.open)
            if cfg.fixed_money:
                unite = _vers_usd(contrat, cfg.symbole, b.open)     # perte par lot et par 1,0 de prix
                fx = compute_fixed_money(solde, cfg.sl_money, cfg.tp_money, unite, sl_d, lot_min,
                                         pas_lot, lot_max, sl_dist_min=spread_prix * 3.0,
                                         tp_dist_min=spread_prix)
                lot = fx
                if fx.ok:
                    sl_d, tp_d = fx.sl_dist, fx.tp_dist
            else:
                lot = compute_lot(solde, cfg.risque_pct, perte_lot, lot_min, pas_lot, lot_max)
            if not lot.ok:
                ignores["lot_trop_gros"] += 1
            else:
                sl = entree - sl_d if d.action == "BUY" else entree + sl_d
                tp = entree + tp_d if d.action == "BUY" else entree - tp_d
                position = {"sens": d.action, "entree": entree, "sl": sl, "tp": tp,
                            "lot": lot.volume, "ouverture": b.time, "signal": d.signal,
                            "spread": spread_prix}
                trades_jour += 1

        # --- 2) La position touche-t-elle son SL ou son TP pendant cette bougie ?
        if position is not None:
            p = position
            sortie, raison = None, ""
            if p["sens"] == "BUY":      # un achat se ferme au prix bid (prix des bougies)
                if b.low <= p["sl"]:
                    sortie, raison = p["sl"], "SL"
                elif b.high >= p["tp"]:
                    sortie, raison = p["tp"], "TP"
            else:                       # une vente se ferme au prix ask = bid + spread
                if b.high + spread_prix >= p["sl"]:
                    sortie, raison = p["sl"], "SL"
                elif b.low + spread_prix <= p["tp"]:
                    sortie, raison = p["tp"], "TP"
            if sortie is not None:
                ecart = (sortie - p["entree"]) if p["sens"] == "BUY" else (p["entree"] - sortie)
                brut = _vers_usd(ecart * p["lot"] * contrat, cfg.symbole, sortie)
                frais = cfg.commission_lot * p["lot"]
                net = brut - frais
                solde += net
                courbe.append(solde)
                trades.append({"ouverture": p["ouverture"], "fermeture": b.time, "sens": p["sens"],
                               "signal": p["signal"], "lot": p["lot"], "entree": p["entree"],
                               "sortie": sortie, "raison": raison, "resultat": round(net, 4),
                               "cout_spread": round(_vers_usd(p["spread"] * p["lot"] * contrat,
                                                              cfg.symbole, sortie), 4),
                               "commission": round(frais, 4), "solde": round(solde, 4)})
                position = None
                if net < 0 and cfg.pause_perte_min > 0:
                    pause_jusqu_a = maintenant + timedelta(minutes=cfg.pause_perte_min)
                if solde_debut_jour > 0 and (solde - solde_debut_jour) / solde_debut_jour * 100 <= -cfg.perte_jour_max:
                    arret_jour = True

        # --- 3) Analyse de la bougie i (clôturée) -> entrée éventuelle à i+1
        if position is None and attente is None and i < n - 1 and not arret_jour:
            d = decide_at(ind, i, params)
            if d.action is None:
                continue
            suivante = heures_paris[i + 1]
            if not in_session(suivante, cfg.session_debut, cfg.session_fin):
                ignores["horaire"] += 1
                continue
            anormal, _ = spread_is_abnormal(ind["spread"].iloc[i + 1],
                                            ind["spread"].iloc[max(0, i - 200):i + 1],
                                            cfg.spread_facteur)
            if anormal:
                ignores["spread"] += 1
                continue
            if trades_jour >= cfg.trades_jour_max or (pause_jusqu_a and suivante < pause_jusqu_a):
                ignores["risque"] += 1
                continue
            attente = d

    return {"trades": trades, "courbe": courbe, "solde_final": solde, "ignores": ignores,
            "cfg": cfg, "periode": (ind["time"].iloc[0], ind["time"].iloc[-1]), "bougies": n}


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
def report(res: dict) -> str:
    cfg, trades, courbe = res["cfg"], res["trades"], np.array(res["courbe"])
    nb = len(trades)
    gagnants = [t for t in trades if t["resultat"] > 0]
    perdants = [t for t in trades if t["resultat"] <= 0]
    gains = sum(t["resultat"] for t in gagnants)
    pertes = -sum(t["resultat"] for t in perdants)
    pic = np.maximum.accumulate(courbe)
    dd = (pic - courbe)
    dd_pct = np.where(pic > 0, dd / pic * 100, 0)
    net = res["solde_final"] - cfg.capital
    jours = max(1, (res["periode"][1] - res["periode"][0]).days)
    pf = (gains / pertes) if pertes > 0 else math.inf

    lignes = [
        "=" * 64,
        f" RAPPORT DE BACKTEST : {cfg.symbole}",
        "=" * 64,
        f" Période               : {res['periode'][0]:%d/%m/%Y} -> {res['periode'][1]:%d/%m/%Y} "
        f"({res['bougies']} bougies)",
        f" Capital de départ     : {cfg.capital:.2f} $   | " + (f"montants fixes : +{cfg.tp_money:.2f} / -{cfg.sl_money:.2f} $" if cfg.fixed_money else f"risque/trade : {cfg.risque_pct:g} %")
        + ("   | compte Cent (hypothèse)" if cfg.cent else ""),
        f" Nombre de trades      : {nb}",
        f" Taux de réussite      : {len(gagnants) / nb * 100:.1f} %" if nb else " Taux de réussite      : -",
        f" Gain moyen / perte moy: {gains / max(1, len(gagnants)):.2f} $ / {pertes / max(1, len(perdants)):.2f} $",
        f" Profit factor         : {pf:.2f}" if pf != math.inf else " Profit factor         : infini (aucune perte)",
        f" Résultat NET          : {net:+.2f} $ ({net / cfg.capital * 100:+.1f} %) après spread et frais",
        f"   dont spread payé    : {sum(t['cout_spread'] for t in trades):.2f} $",
        f"   dont commissions    : {sum(t['commission'] for t in trades):.2f} $",
        f" Drawdown maximal      : {dd.max():.2f} $ ({dd_pct.max():.1f} %)",
        f" Moyenne par jour      : {net / jours:+.3f} $ ({net / cfg.capital * 100 / jours:+.3f} %/jour calendaire)",
        f" Signaux ignorés       : horaire {res['ignores']['horaire']}, spread {res['ignores']['spread']}, "
        f"règles de risque {res['ignores']['risque']}, lot minimal trop gros {res['ignores']['lot_trop_gros']}",
        "-" * 64,
        " Rappel : un backtest positif ne garantit AUCUN gain futur.",
        " Étape suivante obligatoire : 1 à 2 mois en compte DÉMO.",
        "=" * 64,
    ]
    if res["ignores"]["lot_trop_gros"] and not cfg.cent:
        lignes.insert(-4, " ! Beaucoup de trades refusés : avec ce capital, le lot minimal 0,01 risque\n"
                          "   trop. Essayez --cent (compte Cent) ou un capital plus élevé.")
    return "\n".join(lignes)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest de la stratégie MonBot")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="fichier CSV de bougies (export MT5 ou simple)")
    src.add_argument("--mt5", action="store_true", help="télécharger depuis MT5 (Windows)")
    src.add_argument("--synthetique", action="store_true", help="données aléatoires (test technique)")
    ap.add_argument("--symbole", default="EURUSD", choices=list(SPECS))
    ap.add_argument("--tf", default="M5", choices=["M1", "M5"])
    ap.add_argument("--mois", type=int, default=6)
    ap.add_argument("--capital", type=float, default=30.0)
    ap.add_argument("--risque", type=float, default=1.0)
    ap.add_argument("--perte-jour", type=float, default=3.0)
    ap.add_argument("--trades-jour", type=int, default=6)
    ap.add_argument("--pause", type=int, default=10)
    ap.add_argument("--debut", default="09:00")
    ap.add_argument("--fin", default="18:00")
    ap.add_argument("--commission", type=float, default=0.0, help="commission aller-retour par lot")
    ap.add_argument("--decalage-serveur", type=float, default=0.0, help="heures serveur - UTC (Exness : 0)")
    ap.add_argument("--cent", action="store_true", help="simuler un compte Cent (hypothèse)")
    ap.add_argument("--tendance", type=int, default=200, choices=[50, 200])
    ap.add_argument("--rr", type=float, default=1.2)
    ap.add_argument("--atr", type=float, default=1.5)
    ap.add_argument("--gain-fixe", type=float, default=None,
                    help="mode montants fixes : gain visé par trade (ex. 0.50)")
    ap.add_argument("--perte-fixe", type=float, default=None,
                    help="mode montants fixes : perte max par trade (ex. 0.70)")
    ap.add_argument("--sortie", default="backtest_resultats", help="dossier des résultats")
    a = ap.parse_args(argv)

    if a.csv:
        df = load_csv(a.csv)
    elif a.mt5:
        df = load_mt5(a.symbole, a.tf, a.mois)
    else:
        print("ATTENTION : données ALÉATOIRES, résultats sans aucune valeur.")
        df = synthetic()

    cfg = Config(symbole=a.symbole, capital=a.capital, risque_pct=min(a.risque, 2.0),
                 perte_jour_max=a.perte_jour, trades_jour_max=a.trades_jour,
                 pause_perte_min=a.pause, session_debut=a.debut, session_fin=a.fin,
                 commission_lot=a.commission, decalage_serveur_h=a.decalage_serveur, cent=a.cent,
                 fixed_money=(a.gain_fixe is not None and a.perte_fixe is not None),
                 tp_money=a.gain_fixe or 0.50, sl_money=a.perte_fixe or 0.70)
    params = StrategyParams(trend_ema=a.tendance, reward_risk=max(1.0, a.rr), atr_sl_mult=a.atr)
    res = run_backtest(df, cfg, params)
    texte = report(res)
    print(texte)

    dossier = Path(a.sortie)
    dossier.mkdir(exist_ok=True)
    horo = datetime.now().strftime("%Y%m%d_%H%M%S")
    pd.DataFrame(res["trades"]).to_csv(dossier / f"trades_{a.symbole}_{horo}.csv",
                                       index=False, sep=";", encoding="utf-8-sig")
    (dossier / f"rapport_{a.symbole}_{horo}.txt").write_text(texte, encoding="utf-8")
    print(f"Résultats enregistrés dans le dossier « {dossier} »")
    return res


if __name__ == "__main__":
    main()
