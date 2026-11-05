"""Tests de la stratégie (données simulées, sans MT5)."""
from datetime import datetime

import numpy as np
import pandas as pd

from bot.strategy import (StrategyParams, adjust_distances, evaluate, in_session,
                          spread_is_abnormal)


def _bougies(closes):
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.0002,
                         "low": np.minimum(o, c) - 0.0002, "close": c})


def test_pas_assez_d_historique():
    d = evaluate(_bougies([1.1] * 50), StrategyParams())
    assert d.action is None


def test_croisement_haussier_donne_achat():
    # Longue hausse (prix > EMA 50), petit repli (EMA 9 passe sous EMA 21), puis reprise
    hausse = list(np.linspace(1.00, 1.10, 300))
    repli = list(np.linspace(1.10, 1.094, 15))
    params = StrategyParams(trend_ema=50, rsi_buy_max=95)
    trouve = None
    prix = hausse + repli
    for k in range(1, 30):
        prix.append(1.094 + k * 0.0006)
        d = evaluate(_bougies(prix), params)
        if d.action == "BUY":
            trouve = d
            break
    assert trouve is not None, "aucun achat détecté"
    assert trouve.sl_distance > 0 and trouve.tp_distance >= trouve.sl_distance


def test_jamais_achat_en_tendance_baissiere_par_croisement():
    prix = list(np.linspace(1.10, 1.00, 400))
    d = evaluate(_bougies(prix), StrategyParams())
    assert d.action != "BUY"


def test_ratio_minimum_1_pour_1():
    sl, tp = adjust_distances(0.0005, 0.0001, 0.0001, 0.0, reward_risk=1.0)
    assert tp >= sl


def test_sl_minimum_spread():
    sl, tp = adjust_distances(0.00005, 0.00005, 0.0002, 0.0, reward_risk=1.2)
    assert sl >= 0.0006 and tp >= sl * 1.2 - 1e-12


def test_filtre_spread():
    anormal, med = spread_is_abnormal(30, [10] * 50, 2.0)
    assert anormal and med == 10
    assert not spread_is_abnormal(15, [10] * 50, 2.0)[0]
    assert not spread_is_abnormal(99, [], 2.0)[0]


def test_plage_horaire():
    lundi_10h = datetime(2026, 11, 9, 10, 0)
    lundi_20h = datetime(2026, 11, 9, 20, 0)
    samedi = datetime(2026, 11, 7, 10, 0)
    assert in_session(lundi_10h, "09:00", "18:00")
    assert not in_session(lundi_20h, "09:00", "18:00")
    assert not in_session(samedi, "09:00", "18:00")
    assert in_session(datetime(2026, 11, 9, 23, 0), "22:00", "02:00")
