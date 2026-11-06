"""
economic_calendar.py : calendrier économique en ligne.

Source : flux public gratuit du calendrier ForexFactory (JSON, sans clé) :
    https://nfs.faireconomy.media/ff_calendar_thisweek.json
C'est un flux NON officiel : il peut changer, être limité ou disparaître. Le bot ne
dépend donc jamais de lui :
  - les données sont gardées sur le disque (rechargées toutes les 6 h, ou quand la
    semaine change) ;
  - si le calendrier est indisponible, le bot utilise les horaires fixes
    (annonces américaines de 14h30 Paris).

Ce module ne dépend pas de MetaTrader5 (testé automatiquement).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
RAFRAICHIR_S = 6 * 3600          # rechargement du flux toutes les 6 heures
REESSAI_S = 30 * 60              # après un échec : nouvel essai dans 30 minutes
IMPACTS = {"Low": 1, "Medium": 2, "High": 3}


@dataclass(frozen=True)
class Event:
    when: datetime               # avec fuseau horaire
    currency: str                # "USD", "EUR"...
    title: str
    impact: str                  # "High" ou "Medium" (ou "Low")


def currencies_for(symboles) -> set[str]:
    """Devises concernées par des symboles : EURUSD -> {EUR, USD}."""
    out: set[str] = set()
    for s in symboles:
        s = "".join(c for c in str(s).upper() if c.isalpha())[:6]
        if len(s) >= 6:
            out.update((s[:3], s[3:6]))
    return out


def parse_events(data) -> list[Event]:
    """Transforme le JSON du flux en événements. Ignore sans planter tout ce qui est invalide."""
    events: list[Event] = []
    if not isinstance(data, list):
        return events
    for e in data:
        try:
            impact = str(e.get("impact", ""))
            if impact not in IMPACTS:               # "Holiday", etc. : ignoré
                continue
            quand = datetime.fromisoformat(str(e["date"]))
            if quand.tzinfo is None:
                continue
            events.append(Event(quand, str(e.get("country", "")).upper(), str(e.get("title", "")), impact))
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    events.sort(key=lambda ev: ev.when)
    return events


def fetch_feed(url: str = URL, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MonBot)",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class NewsCalendar:
    def __init__(self, dossier: Path, journal=None, fetch=fetch_feed, horloge=time.time):
        self.path = Path(dossier) / "calendar_cache.json"
        self.journal = journal
        self._fetch = fetch
        self._horloge = horloge
        self._lock = threading.Lock()
        self._events: list[Event] = []
        self._fetched_at = 0.0
        self._dernier_essai = 0.0
        self._en_cours = False
        self._charger()

    # ------------------------------------------------------------- disque
    def _charger(self) -> None:
        try:
            brut = json.loads(self.path.read_text(encoding="utf-8"))
            self._events = parse_events(brut.get("events"))
            self._fetched_at = float(brut.get("fetched_at", 0.0))
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def _sauver(self, brut) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched_at": self._fetched_at, "events": brut}), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    # ------------------------------------------------------------- réseau (en arrière-plan)
    def _a_rafraichir(self, maintenant_ts: float) -> bool:
        if not self._fetched_at:
            return True
        vieux = maintenant_ts - self._fetched_at > RAFRAICHIR_S
        autre_semaine = (datetime.fromtimestamp(self._fetched_at).isocalendar()[:2]
                         != datetime.fromtimestamp(maintenant_ts).isocalendar()[:2])
        return vieux or autre_semaine

    def refresh_if_needed(self) -> None:
        """Lance le rechargement SANS bloquer le bot (fil séparé). À appeler à chaque cycle."""
        ts = self._horloge()
        with self._lock:
            if self._en_cours or not self._a_rafraichir(ts) or ts - self._dernier_essai < REESSAI_S:
                return
            self._en_cours, self._dernier_essai = True, ts
        threading.Thread(target=self._telecharger, daemon=True).start()

    def _telecharger(self) -> None:
        try:
            brut = self._fetch()
            events = parse_events(brut)
            if not events:
                raise ValueError("calendrier vide")
            with self._lock:
                self._events, self._fetched_at = events, self._horloge()
            self._sauver(brut)
            if self.journal:
                self.journal.info(f"Calendrier économique mis à jour ({len(events)} annonces cette semaine).")
        except Exception as exc:     # réseau coupé, flux changé, limite atteinte...
            if self.journal:
                self.journal.warning(f"Calendrier économique indisponible ({exc}). "
                                     "Horaires fixes d'annonces utilisés en attendant.")
        finally:
            with self._lock:
                self._en_cours = False

    # ------------------------------------------------------------- requêtes
    def available(self, maintenant: datetime) -> bool:
        """Données utilisables : récupérées il y a moins de 8 jours et couvrant la semaine en cours."""
        with self._lock:
            if not self._events or not self._fetched_at:
                return False
            if self._horloge() - self._fetched_at > 8 * 86400:
                return False
            return any(abs((ev.when - maintenant).days) <= 6 for ev in self._events)

    def _filtrer(self, devises: set[str], impact_min: str):
        seuil = IMPACTS.get(impact_min, 3)
        with self._lock:
            return [ev for ev in self._events
                    if IMPACTS.get(ev.impact, 0) >= seuil and (not devises or ev.currency in devises)]

    def blackout(self, maintenant: datetime, devises: set[str], impact_min: str,
                 avant_min: int, apres_min: int) -> Event | None:
        """Annonce qui bloque les entrées maintenant (de 'avant_min' avant à 'apres_min' après)."""
        for ev in self._filtrer(devises, impact_min):
            delta = (maintenant - ev.when).total_seconds() / 60.0
            if -avant_min <= delta <= apres_min:
                return ev
        return None

    def upcoming(self, maintenant: datetime, minutes: float, devises: set[str],
                 impact_min: str) -> list[Event]:
        """Annonces qui arrivent dans les 'minutes' prochaines minutes."""
        return [ev for ev in self._filtrer(devises, impact_min)
                if 0 <= (ev.when - maintenant).total_seconds() / 60.0 <= minutes]

    def next_event(self, maintenant: datetime, devises: set[str], impact_min: str) -> Event | None:
        for ev in self._filtrer(devises, impact_min):
            if ev.when >= maintenant:
                return ev
        return None
