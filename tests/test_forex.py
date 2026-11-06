"""Tests des règles propres au marché Forex."""
from datetime import datetime

from bot.config import Settings
from bot.risk import RiskManager, loss_streak
from bot.strategy import (friday_cutoff_reached, in_news_blackout, market_is_tradable,
                          past_close_time)

LUNDI = datetime(2026, 1, 5)
MERCREDI = datetime(2026, 1, 7)
VENDREDI = datetime(2026, 1, 9)
SAMEDI = datetime(2026, 1, 10)


def test_annonces_americaines():
    assert in_news_blackout(MERCREDI.replace(hour=14, minute=30))
    assert in_news_blackout(MERCREDI.replace(hour=13, minute=30))     # décalage d'heure US/Europe
    assert not in_news_blackout(MERCREDI.replace(hour=14, minute=50))
    assert not in_news_blackout(MERCREDI.replace(hour=11, minute=0))
    assert not in_news_blackout(SAMEDI.replace(hour=14, minute=30))


def test_vendredi_derniere_entree():
    assert friday_cutoff_reached(VENDREDI.replace(hour=17, minute=0), "17:00")
    assert not friday_cutoff_reached(VENDREDI.replace(hour=16, minute=59), "17:00")
    assert not friday_cutoff_reached(MERCREDI.replace(hour=18, minute=0), "17:00")   # pas un vendredi
    assert not friday_cutoff_reached(VENDREDI.replace(hour=20, minute=0), "")        # désactivé


def test_fermeture_avant_rollover():
    assert past_close_time(LUNDI.replace(hour=21, minute=30), "21:30")
    assert not past_close_time(LUNDI.replace(hour=21, minute=29), "21:30")
    assert not past_close_time(SAMEDI.replace(hour=22, minute=0), "21:30")


def test_filtre_de_volatilite():
    spread = 0.0001                                     # 1 pip
    assert not market_is_tradable(0.0003, 0.0004, spread, 4.0, 3.0)[0]   # ATR 3 pips : trop calme
    assert market_is_tradable(0.0006, 0.0005, spread, 4.0, 3.0)[0]
    assert not market_is_tradable(0.0020, 0.0005, spread, 4.0, 3.0)[0]   # 4x la normale : agité
    assert market_is_tradable(0.0003, 0.0001, spread, 0.0, 0.0)[0]       # filtres désactivés


def test_serie_de_pertes():
    assert loss_streak([1, -1, -1, -1]) == 3
    assert loss_streak([-1, -1, 1]) == 0
    assert loss_streak([]) == 0
    rm = RiskManager()
    assert not rm.check_loss_streak(3, 4) and not rm.halted
    assert rm.check_loss_streak(4, 4) and rm.halted


def test_reglages_forex_valides():
    s = Settings.from_dict({"friday_last_entry": "", "rollover_close_time": "25:99",
                            "min_atr_spread_ratio": -5, "max_consecutive_losses": 0})
    assert s.friday_last_entry == ""                    # vide = désactivé, accepté
    assert s.rollover_close_time == "21:30"             # format faux -> remis par défaut
    assert s.min_atr_spread_ratio == 0.0 and s.max_consecutive_losses == 1
    d = Settings()
    assert d.close_before_rollover and d.news_blackout and d.max_consecutive_losses == 4
