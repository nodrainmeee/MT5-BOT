"""
api.py : le "pont" entre l'interface HTML (JavaScript) et le code Python.

Chaque méthode publique de la classe Api peut être appelée depuis le
JavaScript avec :  await window.pywebview.api.nom_de_la_methode(...)

Attention : pywebview expose aussi les ATTRIBUTS publics. C'est pourquoi
tous les attributs internes commencent par "_" (ils restent invisibles).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from . import __version__
from .config import (SYMBOLES_DISPONIBLES, TEXTE_CONFIRMATION_REEL, ConfigStore,
                     delete_password, load_password, save_password)

# Champs que l'interface a le droit de modifier via save_settings()
CHAMPS_MODIFIABLES = {
    "symbols", "timeframe", "risk_per_trade", "daily_loss_max", "max_trades_per_day",
    "pause_after_loss_min", "max_total_positions", "session_start", "session_end",
    "trend_ema", "rsi_buy_max", "rsi_sell_min", "atr_sl_mult", "reward_risk",
    "spread_factor_max", "news_pause_min",
    "fixed_money_mode", "fixed_tp_money", "fixed_sl_money",
}


class Api:
    def __init__(self, store: ConfigStore, journal, engine, dossier_donnees):
        self._store = store
        self._journal = journal
        self._engine = engine
        self._dossier = dossier_donnees

    # ------------------------------------------------------------------ lecture
    def get_initial(self) -> dict:
        s = self._store.get()
        return {
            "version": __version__,
            "settings": s.to_dict(),
            "symbols": SYMBOLES_DISPONIBLES,
            "has_saved_password": bool(s.remember_credentials and s.mt5_login
                                       and load_password(s.mt5_login)),
            "confirm_text": TEXTE_CONFIRMATION_REEL,
            "data_dir": str(self._dossier),
        }

    def get_state(self, dernier_id_journal: int = 0) -> dict:
        etat = self._engine.snapshot()
        s = self._store.get()
        etat["max_trades"] = s.max_trades_per_day
        etat["real_mode_enabled"] = s.real_mode_enabled
        etat["logs"] = self._journal.get_since(dernier_id_journal)
        return etat

    def get_trades(self) -> list:
        return self._journal.recent_trades(30)

    # ------------------------------------------------------------------ réglages
    def save_settings(self, donnees: dict) -> dict:
        propres = {k: v for k, v in (donnees or {}).items() if k in CHAMPS_MODIFIABLES}
        notes = self._store.update(propres)
        for n in notes:
            self._journal.warning(f"Réglage corrigé : {n}")
        self._journal.info("Réglages enregistrés (appliqués dès le prochain cycle).")
        return {"ok": True, "notes": notes, "settings": self._store.get().to_dict()}

    def set_theme(self, theme: str) -> bool:
        self._store.update({"theme": "light" if theme == "light" else "dark"})
        return True

    def enable_real_mode(self, texte: str) -> dict:
        if self._engine.is_running():
            return {"ok": False, "message": "Arrêtez d'abord le bot."}
        if (texte or "").strip().upper() != TEXTE_CONFIRMATION_REEL:
            return {"ok": False, "message": f"Tapez exactement : {TEXTE_CONFIRMATION_REEL}"}
        self._store.update({"real_mode_enabled": True})
        self._journal.warning("MODE RÉEL ACTIVÉ par l'utilisateur. Les règles de risque restent actives.")
        return {"ok": True, "message": "Mode réel activé"}

    def disable_real_mode(self) -> dict:
        self._store.update({"real_mode_enabled": False})
        self._journal.info("Retour au mode démo (les comptes réels seront refusés).")
        return {"ok": True}

    # ------------------------------------------------------------------ bot
    def start_bot(self, identifiants: dict) -> dict:
        identifiants = identifiants or {}
        login = str(identifiants.get("login", "")).strip()
        mdp = identifiants.get("password", "") or ""
        serveur = str(identifiants.get("server", "")).strip()
        memoriser = bool(identifiants.get("remember", False))
        if login and not login.isdigit():
            return {"ok": False, "message": "Le numéro de compte ne contient que des chiffres."}
        if login and not mdp:
            mdp = load_password(login) or ""
            if not mdp:
                return {"ok": False, "message": "Mot de passe manquant pour ce compte."}
        if login and memoriser:
            if not save_password(login, mdp):
                self._journal.warning("Impossible d'enregistrer le mot de passe dans le "
                                      "Gestionnaire d'identifiants Windows.")
        self._store.update({"mt5_login": login, "mt5_server": serveur,
                            "remember_credentials": memoriser and bool(login)})
        s = self._store.get()
        ok, msg = self._engine.start(login, mdp, serveur, s.mt5_path)
        return {"ok": ok, "message": msg}

    def stop_bot(self) -> dict:
        self._engine.stop()
        return {"ok": True}

    def emergency_stop(self) -> dict:
        self._journal.error("ARRÊT D'URGENCE demandé.")
        self._engine.stop("arrêt d'urgence")
        return {"ok": True, "open_positions": self._engine.open_positions_count()}

    def close_all_positions(self) -> dict:
        return self._engine.close_all_positions()

    def pause_news(self, minutes: int) -> dict:
        try:
            minutes = max(5, min(240, int(minutes)))
        except (TypeError, ValueError):
            minutes = self._store.get().news_pause_min
        self._engine.pause_news(minutes)
        return {"ok": True, "minutes": minutes}

    def resume(self) -> dict:
        self._engine.resume()
        return {"ok": True}

    def forget_credentials(self) -> dict:
        s = self._store.get()
        if s.mt5_login:
            delete_password(s.mt5_login)
        self._store.update({"remember_credentials": False, "mt5_login": "", "mt5_server": ""})
        self._journal.info("Identifiants oubliés.")
        return {"ok": True}

    # ------------------------------------------------------------------ fichiers
    def open_data_folder(self) -> bool:
        try:
            if sys.platform == "win32":
                os.startfile(str(self._dossier))   # ouvre l'Explorateur Windows
            else:
                subprocess.Popen(["xdg-open", str(self._dossier)])
            return True
        except Exception:
            return False

    def export_trades_csv(self) -> dict:
        nom = f"trades_{datetime.now():%Y%m%d_%H%M%S}.csv"
        chemin = self._journal.export_trades_csv(self._dossier / nom)
        self._journal.info(f"Trades exportés : {chemin}")
        return {"ok": True, "path": str(chemin)}
