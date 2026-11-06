"""Tests du calendrier économique (sans accès réseau : le flux est simulé)."""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.economic_calendar import NewsCalendar, currencies_for, parse_events

PARIS = timezone(timedelta(hours=1))
FLUX = [
    {"title": "Core CPI m/m", "country": "USD", "date": "2026-01-07T08:30:00-05:00", "impact": "High"},
    {"title": "German Ifo", "country": "EUR", "date": "2026-01-07T04:00:00-05:00", "impact": "Medium"},
    {"title": "Bank Holiday", "country": "GBP", "date": "2026-01-07T00:00:00-05:00", "impact": "Holiday"},
    {"title": "Cassé", "country": "USD", "date": "pas une date", "impact": "High"},
    {"title": "Sans fuseau", "country": "USD", "date": "2026-01-07T08:30:00", "impact": "High"},
]


def _cal(fetch=lambda: FLUX, ts=1_767_000_000.0):
    return NewsCalendar(Path(tempfile.mkdtemp()), None, fetch=fetch, horloge=lambda: ts)


def test_lecture_du_flux_ignore_les_lignes_invalides():
    ev = parse_events(FLUX)
    assert [e.title for e in ev] == ["German Ifo", "Core CPI m/m"]     # triées par heure
    assert ev[1].when.astimezone(PARIS) == datetime(2026, 1, 7, 14, 30, tzinfo=PARIS)
    assert parse_events("n'importe quoi") == [] and parse_events(None) == []


def test_devises_des_symboles():
    assert currencies_for(["EURUSD", "XAUUSD"]) == {"EUR", "USD", "XAU"}
    assert currencies_for(["EURUSDm"]) == {"EUR", "USD"}                # suffixe du broker


def test_blocage_autour_d_une_annonce():
    c = _cal(); c._events = parse_events(FLUX)
    cpi = datetime(2026, 1, 7, 14, 30, tzinfo=PARIS)
    eur_usd = {"EUR", "USD"}
    assert c.blackout(cpi - timedelta(minutes=10), eur_usd, "High", 15, 15)
    assert c.blackout(cpi + timedelta(minutes=14), eur_usd, "High", 15, 15)
    assert not c.blackout(cpi - timedelta(minutes=20), eur_usd, "High", 15, 15)
    assert not c.blackout(cpi + timedelta(minutes=16), eur_usd, "High", 15, 15)
    assert not c.blackout(cpi, {"GBP", "JPY"}, "High", 15, 15)           # autre devise : pas concerné
    # L'annonce "Medium" ne compte que si on le demande
    ifo = datetime(2026, 1, 7, 10, 0, tzinfo=PARIS)
    assert not c.blackout(ifo, {"EUR"}, "High", 15, 15)
    assert c.blackout(ifo, {"EUR"}, "Medium", 15, 15)


def test_annonce_imminente_et_prochaine():
    c = _cal(); c._events = parse_events(FLUX)
    cpi = datetime(2026, 1, 7, 14, 30, tzinfo=PARIS)
    assert c.upcoming(cpi - timedelta(minutes=2), 3, {"USD"}, "High")
    assert not c.upcoming(cpi - timedelta(minutes=5), 3, {"USD"}, "High")
    assert c.next_event(cpi - timedelta(hours=3), {"USD"}, "High").title == "Core CPI m/m"
    assert c.next_event(cpi + timedelta(minutes=1), {"USD"}, "High") is None


def test_telechargement_cache_et_repli():
    ts = datetime(2026, 1, 7, 12, 0, tzinfo=PARIS).timestamp()
    c = _cal(ts=ts)
    maintenant = datetime(2026, 1, 7, 12, 0, tzinfo=PARIS)
    assert not c.available(maintenant)                                   # rien de chargé : repli horaires fixes
    c._telecharger()
    assert c.available(maintenant)
    # relancé plus tard : les données reviennent du disque, sans réseau
    c2 = NewsCalendar(c.path.parent, None, fetch=lambda: (_ for _ in ()).throw(OSError("hors ligne")),
                      horloge=lambda: ts)
    assert c2.available(maintenant)
    # flux en panne et pas de cache : indisponible, sans planter
    c3 = _cal(fetch=lambda: (_ for _ in ()).throw(OSError("hors ligne")), ts=ts)
    c3._telecharger()
    assert not c3.available(maintenant)
    # flux vide : refusé (on garde l'ancien)
    c4 = _cal(fetch=lambda: [], ts=ts); c4._telecharger()
    assert not c4.available(maintenant)


def test_reglages_calendrier():
    from bot.config import Settings
    s = Settings.from_dict({"news_impact": "Low", "news_margin_min": 1})
    assert s.news_impact == "High" and s.news_margin_min == 5
    assert Settings().news_calendar_online
