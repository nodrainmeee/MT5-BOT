"""Tests de la gestion du risque (données simulées, sans MT5)."""
from datetime import date, datetime, timedelta

from bot.config import Settings
from bot.risk import RiskManager, compute_lot


def test_lot_arrondi_vers_le_bas():
    # 1000 $ x 1 % = 10 $ ; 1 lot perd 150 $ au SL -> 0,0666 lot -> 0,06
    r = compute_lot(1000, 1.0, 150.0, 0.01, 0.01, 100)
    assert r.ok and r.volume == 0.06
    assert r.risk_amount <= 10.0


def test_lot_minimal_trop_risque_refuse():
    # 30 $ x 1 % = 0,30 $ ; 0,01 lot perd 1,50 $ -> refus (c'est le cas d'un petit compte standard)
    r = compute_lot(30, 1.0, 150.0, 0.01, 0.01, 100)
    assert not r.ok and r.volume == 0.0
    assert "refusé" in r.reason


def test_lot_maximal_respecte():
    r = compute_lot(10_000_000, 1.0, 1.0, 0.01, 0.01, 50)
    assert r.volume == 50


def test_pas_de_lot_011():
    r = compute_lot(1000, 1.0, 10.0, 0.1, 0.1, 100)   # brut = 1,0 lot
    assert r.volume == 1.0


def test_perte_max_du_jour_arrete():
    rm = RiskManager()
    rm.sync(date(2026, 1, 5), solde=97.0, realise=-3.0, nb_trades=3)   # départ = 100
    assert rm.start_balance == 100.0
    assert rm.check_daily_loss(flottant=0.0, perte_max_pct=3.0) is True
    ok, raison = rm.can_open("EURUSD", datetime(2026, 1, 5, 10), {}, 0, 6, 2)
    assert not ok and "Perte maximale" in raison


def test_nouveau_jour_remet_a_zero():
    rm = RiskManager()
    rm.sync(date(2026, 1, 5), 97.0, -3.0, 3)
    rm.check_daily_loss(0.0, 3.0)
    rm.sync(date(2026, 1, 6), 97.0, 0.0, 0)
    assert rm.halted is False and rm.trades_today == 0


def test_pause_apres_perte():
    rm = RiskManager()
    rm.sync(date(2026, 1, 5), 100.0, 0.0, 0)
    t = datetime(2026, 1, 5, 10, 0)
    rm.register_loss(t, 10)
    assert not rm.can_open("EURUSD", t + timedelta(minutes=5), {}, 0, 6, 2)[0]
    assert rm.can_open("EURUSD", t + timedelta(minutes=11), {}, 0, 6, 2)[0]


def test_max_trades_et_positions():
    rm = RiskManager()
    rm.sync(date(2026, 1, 5), 100.0, 0.0, 6)
    t = datetime(2026, 1, 5, 10)
    assert not rm.can_open("EURUSD", t, {}, 0, 6, 2)[0]          # 6/6 trades
    rm2 = RiskManager()
    rm2.sync(date(2026, 1, 5), 100.0, 0.0, 0)
    assert not rm2.can_open("EURUSD", t, {"EURUSD": 1}, 1, 6, 2)[0]   # déjà une position
    assert not rm2.can_open("GBPUSD", t, {"EURUSD": 1, "USDJPY": 1}, 2, 6, 2)[0]  # total atteint
    assert rm2.can_open("GBPUSD", t, {"EURUSD": 1}, 1, 6, 2)[0]


def test_plafonds_reglages():
    s = Settings.from_dict({"risk_per_trade": 50, "daily_loss_max": 90, "reward_risk": 0.5,
                            "max_trades_per_day": 999, "timeframe": "H1"})
    assert s.risk_per_trade == 2.0
    assert s.daily_loss_max == 10.0
    assert s.reward_risk == 1.0
    assert s.max_trades_per_day == 20
    assert s.timeframe == "M5"
    assert s.real_mode_enabled is False    # démo par défaut


def test_montants_fixes_eurusd_lot_min():
    from bot.risk import compute_fixed_money
    # EURUSD : 1 lot perd 100 000 $ par 1,0 de prix ; 0,01 lot -> 1 000 $ par 1,0
    r = compute_fixed_money(30.0, 0.70, 0.50, 100_000.0, 0.0009, 0.01, 0.01, 200.0,
                            sl_dist_min=0.0003, tp_dist_min=0.0001)
    assert r.ok and r.volume == 0.01
    assert abs(r.sl_dist - 0.0007) < 1e-9      # 7 pips = 0,70 $
    assert abs(r.tp_dist - 0.0005) < 1e-9      # 5 pips = 0,50 $


def test_montants_fixes_refus():
    from bot.risk import compute_fixed_money
    # perte fixe trop grosse pour le capital (plafond 3 %)
    assert not compute_fixed_money(10.0, 0.70, 0.50, 100_000.0, 0.0009, 0.01, 0.01, 200.0).ok
    # distance trop proche du spread -> refus
    assert not compute_fixed_money(30.0, 0.70, 0.50, 100_000.0, 0.0009, 0.01, 0.01, 200.0,
                                   sl_dist_min=0.0010).ok


def test_perte_jour_pire_cas():
    rm = RiskManager()
    rm.sync(date(2026, 1, 5), 30.0, 0.0, 0)
    assert rm.can_risk_amount(0.0, 0.70, 3.0)[0]        # -0,70 sur limite -0,90 : OK
    assert not rm.can_risk_amount(-0.70, 0.70, 3.0)[0]  # -1,40 dépasserait -0,90
