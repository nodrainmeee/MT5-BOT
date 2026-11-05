"""Tests des indicateurs (données simulées, sans MT5)."""
import numpy as np
import pandas as pd

from bot.indicators import add_indicators, atr, ema, rsi


def test_ema_constante():
    s = pd.Series([1.5] * 100)
    assert np.allclose(ema(s, 21), 1.5)


def test_ema_formule():
    s = pd.Series([1.0, 2.0, 3.0])
    e = ema(s, 3)                       # alpha = 2/(3+1) = 0.5
    assert np.isclose(e.iloc[1], 1.5)
    assert np.isclose(e.iloc[2], 2.25)


def test_rsi_bornes_et_extremes():
    hausse = pd.Series(np.arange(1, 101, dtype=float))
    baisse = hausse[::-1].reset_index(drop=True)
    assert rsi(hausse).iloc[-1] == 100.0
    assert rsi(baisse).iloc[-1] < 1.0
    aleatoire = pd.Series(np.cumsum(np.random.default_rng(1).normal(size=500)) + 100)
    r = rsi(aleatoire).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_positif():
    rng = np.random.default_rng(2)
    c = pd.Series(100 + np.cumsum(rng.normal(size=300)))
    h, l = c + 0.5, c - 0.5
    a = atr(h, l, c)
    assert (a.iloc[20:] > 0).all()


def test_add_indicators_colonnes():
    df = pd.DataFrame({"open": [1.0] * 60, "high": [1.1] * 60, "low": [0.9] * 60, "close": [1.0] * 60})
    out = add_indicators(df, 50)
    for col in ("ema9", "ema21", "ema50", "ema_trend", "rsi", "atr"):
        assert col in out.columns
    assert "ema9" not in df.columns    # l'original n'est pas modifié
