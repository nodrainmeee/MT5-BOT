"""
strategy.py : la stratégie de scalping (cahier des charges §5).

Signal A (croisement) : l'EMA 9 croise l'EMA 21 dans le sens de la tendance
                        de fond (prix au-dessus/en dessous de l'EMA 50 ou 200).
Signal B (rebond)     : en tendance haussière (prix > EMA 50 et EMA 21 > EMA 50),
                        la bougie touche l'EMA 21 puis clôture au-dessus, en
                        bougie verte. Inverse pour la baisse.
Entrée                : signal A OU signal B, puis filtre RSI.
Sorties               : stop loss = ATR x multiplicateur ; take profit = stop
                        loss x ratio (toujours >= 1).

Important : la stratégie ne regarde QUE des bougies clôturées (jamais la
bougie en cours de formation), sinon un signal pourrait apparaître puis
disparaître dans la même minute.

Ce module ne dépend pas de MetaTrader5 : il est testé automatiquement et
réutilisé à l'identique par le backtest.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .config import parse_hhmm
from .indicators import add_indicators


@dataclass
class StrategyParams:
    trend_ema: int = 200
    rsi_buy_max: float = 75.0
    rsi_sell_min: float = 25.0
    atr_sl_mult: float = 1.5
    reward_risk: float = 1.2

    @classmethod
    def from_settings(cls, s) -> "StrategyParams":
        return cls(trend_ema=s.trend_ema, rsi_buy_max=s.rsi_buy_max,
                   rsi_sell_min=s.rsi_sell_min, atr_sl_mult=s.atr_sl_mult,
                   reward_risk=s.reward_risk)


@dataclass
class Decision:
    """Résultat de l'analyse d'une bougie."""
    action: str | None          # "BUY", "SELL" ou None (pas de trade)
    signal: str = ""            # "A", "B" ou "A+B"
    reason: str = ""            # explication lisible (affichée dans le journal)
    sl_distance: float = 0.0    # distance du stop loss, en prix
    tp_distance: float = 0.0    # distance du take profit, en prix
    atr: float = 0.0
    rsi: float = 0.0
    is_filtered: bool = False   # True = il y avait un signal mais un filtre l'a bloqué


def bars_needed(params: StrategyParams) -> int:
    """Nombre minimal de bougies pour que les indicateurs soient fiables."""
    return int(params.trend_ema) + 50


def decide_at(ind: pd.DataFrame, i: int, params: StrategyParams) -> Decision:
    """Analyse la bougie clôturée n° i d'un tableau qui contient déjà les indicateurs."""
    if i < 1 or i < bars_needed(params) - 1:
        return Decision(None, reason="Pas assez d'historique pour calculer les indicateurs")

    b = ind.iloc[i]       # bougie analysée (clôturée)
    p = ind.iloc[i - 1]   # bougie précédente

    valeurs = [b.ema9, b.ema21, b.ema50, b.ema_trend, b.rsi, b.atr, p.ema9, p.ema21]
    if any(pd.isna(v) for v in valeurs) or b.atr <= 0:
        return Decision(None, reason="Indicateurs indisponibles")

    # --- Signal A : croisement EMA 9 / EMA 21 dans le sens de la tendance ---
    croise_hausse = p.ema9 <= p.ema21 and b.ema9 > b.ema21
    croise_baisse = p.ema9 >= p.ema21 and b.ema9 < b.ema21
    a_achat = croise_hausse and b.close > b.ema_trend
    a_vente = croise_baisse and b.close < b.ema_trend

    # --- Signal B : rebond sur l'EMA 21 dans la tendance (EMA 50) ---
    b_achat = (b.close > b.ema50 and b.ema21 > b.ema50
               and b.low <= b.ema21 and b.close > b.ema21 and b.close > b.open)
    b_vente = (b.close < b.ema50 and b.ema21 < b.ema50
               and b.high >= b.ema21 and b.close < b.ema21 and b.close < b.open)

    achat = a_achat or b_achat
    vente = a_vente or b_vente
    rsi_v, atr_v = float(b.rsi), float(b.atr)

    if achat and vente:  # cas théorique (signaux contradictoires) : on s'abstient
        return Decision(None, reason="Signaux contradictoires, abstention",
                        atr=atr_v, rsi=rsi_v, is_filtered=True)
    if not achat and not vente:
        return Decision(None, reason="Aucun signal", atr=atr_v, rsi=rsi_v)

    if achat:
        nom = "A+B" if (a_achat and b_achat) else ("A" if a_achat else "B")
        if rsi_v > params.rsi_buy_max:
            return Decision(None, signal=nom, atr=atr_v, rsi=rsi_v, is_filtered=True,
                            reason=f"Achat (signal {nom}) ignoré : RSI {rsi_v:.1f} > {params.rsi_buy_max:g}")
        action = "BUY"
    else:
        nom = "A+B" if (a_vente and b_vente) else ("A" if a_vente else "B")
        if rsi_v < params.rsi_sell_min:
            return Decision(None, signal=nom, atr=atr_v, rsi=rsi_v, is_filtered=True,
                            reason=f"Vente (signal {nom}) ignorée : RSI {rsi_v:.1f} < {params.rsi_sell_min:g}")
        action = "SELL"

    sl = atr_v * params.atr_sl_mult
    tp = sl * max(1.0, params.reward_risk)
    libelle = "Achat" if action == "BUY" else "Vente"
    return Decision(action, signal=nom, sl_distance=sl, tp_distance=tp, atr=atr_v, rsi=rsi_v,
                    reason=f"{libelle} : signal {nom} (RSI {rsi_v:.1f})")


def evaluate(bougies_cloturees: pd.DataFrame, params: StrategyParams) -> Decision:
    """Analyse la DERNIÈRE bougie clôturée d'un tableau open/high/low/close."""
    if len(bougies_cloturees) < bars_needed(params):
        return Decision(None, reason=f"Pas assez d'historique ({len(bougies_cloturees)} bougies)")
    ind = add_indicators(bougies_cloturees, params.trend_ema)
    return decide_at(ind, len(ind) - 1, params)


# ---------------------------------------------------------------------------
# Filtres communs au bot et au backtest
# ---------------------------------------------------------------------------
def adjust_distances(sl: float, tp: float, spread_prix: float, stops_level_prix: float,
                     reward_risk: float, spread_mult_min: float = 3.0) -> tuple[float, float]:
    """Applique les minimums de distance pour le stop loss et le take profit.

    - Le stop loss doit valoir au moins 3 spreads (sinon le spread "mange"
      le trade) et respecter la distance minimale imposée par le broker
      (stops level).
    - Le take profit est recalculé pour garder un ratio >= 1:1.
    """
    sl_min = max(spread_prix * spread_mult_min, stops_level_prix + spread_prix)
    sl = max(sl, sl_min)
    tp = max(tp, sl * max(1.0, reward_risk), stops_level_prix + spread_prix)
    return sl, tp


def spread_is_abnormal(spread_actuel: float, historique: list | pd.Series,
                       facteur_max: float) -> tuple[bool, float]:
    """Le spread actuel est-il anormalement élevé ?

    "Normal" = médiane des spreads des dernières bougies. Renvoie
    (anormal ?, médiane). Si on n'a pas d'historique, on ne bloque pas.
    """
    serie = pd.Series(list(historique), dtype="float64").dropna()
    serie = serie[serie > 0]
    if serie.empty:
        return False, 0.0
    mediane = float(serie.median())
    if mediane <= 0 or math.isnan(mediane):
        return False, 0.0
    return spread_actuel > mediane * facteur_max, mediane


def in_session(maintenant: datetime, debut: str, fin: str) -> bool:
    """Vrai si 'maintenant' (heure de Paris) est dans la plage horaire,
    du lundi au vendredi. Gère aussi une plage qui passe minuit (ex. 22:00-02:00)."""
    if maintenant.weekday() >= 5:      # samedi (5) ou dimanche (6)
        return False
    d, f = parse_hhmm(debut), parse_hhmm(fin)
    if d is None or f is None:
        return False
    minutes = maintenant.hour * 60 + maintenant.minute
    m_d, m_f = d[0] * 60 + d[1], f[0] * 60 + f[1]
    if m_d <= m_f:
        return m_d <= minutes < m_f
    return minutes >= m_d or minutes < m_f
