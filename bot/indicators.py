"""
indicators.py : calcul des indicateurs techniques (EMA, RSI, ATR).

Ce module n'utilise PAS MetaTrader5 : il fonctionne avec de simples
tableaux pandas. C'est ce qui permet de le tester sur GitHub (sans MT5)
et de le réutiliser tel quel dans le backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(serie: pd.Series, periode: int) -> pd.Series:
    """Moyenne mobile exponentielle (même formule que MT5 : alpha = 2/(n+1))."""
    return serie.ewm(span=periode, adjust=False).mean()


def rsi(cloture: pd.Series, periode: int = 14) -> pd.Series:
    """RSI de Wilder (comme dans MT5). Valeur entre 0 et 100."""
    delta = cloture.diff()
    gain = delta.clip(lower=0.0)
    perte = -delta.clip(upper=0.0)
    # Lissage de Wilder = moyenne exponentielle avec alpha = 1/période
    moy_gain = gain.ewm(alpha=1.0 / periode, adjust=False).mean()
    moy_perte = perte.ewm(alpha=1.0 / periode, adjust=False).mean()
    rs = moy_gain / moy_perte.replace(0.0, np.nan)
    resultat = 100.0 - 100.0 / (1.0 + rs)
    # Aucune perte sur la période : RSI = 100 (et 50 s'il n'y a eu aucun mouvement)
    resultat = resultat.where(moy_perte != 0.0, 100.0)
    resultat = resultat.where(~((moy_perte == 0.0) & (moy_gain == 0.0)), 50.0)
    return resultat


def atr(haut: pd.Series, bas: pd.Series, cloture: pd.Series, periode: int = 14) -> pd.Series:
    """Average True Range (volatilité moyenne), lissage de Wilder."""
    cloture_prec = cloture.shift(1)
    true_range = pd.concat([haut - bas,
                            (haut - cloture_prec).abs(),
                            (bas - cloture_prec).abs()], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / periode, adjust=False).mean()


def add_indicators(df: pd.DataFrame, trend_period: int = 200) -> pd.DataFrame:
    """Ajoute toutes les colonnes d'indicateurs utilisées par la stratégie.

    Le tableau doit contenir les colonnes : open, high, low, close.
    Renvoie une copie (le tableau d'origine n'est pas modifié).
    """
    out = df.copy()
    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["ema50"] = ema(out["close"], 50)
    out["ema_trend"] = ema(out["close"], int(trend_period))
    out["rsi"] = rsi(out["close"], 14)
    out["atr"] = atr(out["high"], out["low"], out["close"], 14)
    return out
