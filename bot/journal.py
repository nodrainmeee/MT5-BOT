"""
journal.py : journal des événements et des trades.

- Chaque événement est écrit dans 3 endroits :
  1. un fichier texte %APPDATA%\\MonBot\\logs\\monbot.log (avec rotation) ;
  2. une base SQLite %APPDATA%\\MonBot\\monbot.db (table "events") ;
  3. une liste en mémoire, lue par l'interface pour le "journal en direct".
- Les trades sont enregistrés dans la table "trades" de la même base.
- Rien n'est envoyé sur Internet (cahier des charges §8).
"""
from __future__ import annotations

import csv
import logging
import sqlite3
import sys
import threading
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Niveaux affichés dans l'interface (le texte du badge est en français)
NIVEAUX = {"info", "success", "warning", "error", "signal"}


class Journal:
    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        (self.dossier / "logs").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=500)   # 500 dernières lignes pour l'interface
        self._next_id = 1

        # --- Fichier texte ---
        self._logger = logging.getLogger("MonBot")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            fh = RotatingFileHandler(self.dossier / "logs" / "monbot.log",
                                     maxBytes=1_000_000, backupCount=5, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self._logger.addHandler(fh)
            # En mode sans console (--windowed), sys.stdout vaut None :
            # on n'ajoute un affichage console que s'il existe vraiment.
            if sys.stdout is not None:
                self._logger.addHandler(logging.StreamHandler(sys.stdout))

        # --- Base SQLite ---
        # check_same_thread=False car le bot (thread séparé) et l'interface
        # écrivent tous les deux ; le verrou self._lock évite les collisions.
        self._db = sqlite3.connect(self.dossier / "monbot.db", check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT)""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS trades(
            ticket INTEGER PRIMARY KEY, ts_open TEXT, ts_close TEXT, symbol TEXT,
            direction TEXT, volume REAL, price_open REAL, sl REAL, tp REAL,
            price_close REAL, profit REAL, signal TEXT, close_reason TEXT)""")
        self._db.commit()

    # ------------------------------------------------------------------ événements
    def log(self, message: str, level: str = "info") -> None:
        level = level if level in NIVEAUX else "info"
        maintenant = datetime.now()
        with self._lock:
            item = {"id": self._next_id, "time": maintenant.strftime("%H:%M:%S"),
                    "level": level, "message": message}
            self._next_id += 1
            self._buffer.append(item)
            try:
                self._db.execute("INSERT INTO events(ts, level, message) VALUES (?,?,?)",
                                 (maintenant.isoformat(timespec="seconds"), level, message))
                self._db.commit()
            except sqlite3.Error:
                pass
        py_level = {"error": logging.ERROR, "warning": logging.WARNING}.get(level, logging.INFO)
        self._logger.log(py_level, message)

    def info(self, m): self.log(m, "info")
    def success(self, m): self.log(m, "success")
    def warning(self, m): self.log(m, "warning")
    def error(self, m): self.log(m, "error")
    def signal(self, m): self.log(m, "signal")

    def get_since(self, dernier_id: int) -> list[dict]:
        """Lignes du journal plus récentes que dernier_id (pour l'interface)."""
        with self._lock:
            return [x for x in self._buffer if x["id"] > int(dernier_id or 0)]

    # ------------------------------------------------------------------ trades
    def record_trade_open(self, ticket, symbol, direction, volume, price, sl, tp, signal):
        with self._lock:
            try:
                self._db.execute(
                    """INSERT OR REPLACE INTO trades(ticket, ts_open, symbol, direction, volume,
                       price_open, sl, tp, signal) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (int(ticket), datetime.now().isoformat(timespec="seconds"), symbol,
                     direction, float(volume), float(price), float(sl), float(tp), signal))
                self._db.commit()
            except sqlite3.Error:
                pass

    def record_trade_close(self, ticket, price_close, profit, reason):
        with self._lock:
            try:
                self._db.execute(
                    """UPDATE trades SET ts_close=?, price_close=?, profit=?, close_reason=?
                       WHERE ticket=?""",
                    (datetime.now().isoformat(timespec="seconds"), float(price_close),
                     float(profit), reason, int(ticket)))
                self._db.commit()
            except sqlite3.Error:
                pass

    def recent_trades(self, limite: int = 50) -> list[dict]:
        with self._lock:
            cur = self._db.execute(
                """SELECT ticket, ts_open, ts_close, symbol, direction, volume, price_open,
                          sl, tp, price_close, profit, signal, close_reason
                   FROM trades ORDER BY ts_open DESC LIMIT ?""", (int(limite),))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def export_trades_csv(self, chemin: Path) -> Path:
        """Exporte tous les trades en CSV (lisible dans Excel, séparateur ;)."""
        lignes = self.recent_trades(limite=100000)
        chemin = Path(chemin)
        with chemin.open("w", newline="", encoding="utf-8-sig") as f:
            if lignes:
                w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()), delimiter=";")
                w.writeheader()
                w.writerows(lignes)
            else:
                f.write("Aucun trade enregistré\n")
        return chemin

    def close(self):
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
