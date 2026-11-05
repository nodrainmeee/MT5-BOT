"""
config.py : réglages de l'utilisateur, chemins de l'application et
stockage sécurisé des identifiants MT5.

Règles respectées (cahier des charges, §3 et §8) :
- les réglages sont enregistrés dans %APPDATA%\\MonBot\\config.json,
  jamais dans le dossier du programme ;
- le mot de passe MT5 n'est JAMAIS écrit dans un fichier : s'il est
  mémorisé, il va dans le Gestionnaire d'identifiants Windows (keyring) ;
- toutes les valeurs saisies sont vérifiées et bornées par des plafonds
  impossibles à dépasser (gestion du risque non désactivable).
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# ---------------------------------------------------------------------------
# Constantes générales
# ---------------------------------------------------------------------------
APP_NAME = "MonBot"

# Numéro "magique" écrit sur chaque ordre du bot. Il permet de reconnaître
# les positions ouvertes par MonBot (et de ne jamais toucher à vos trades
# manuels). Ne le changez pas une fois que le bot a des positions ouvertes.
MAGIC_NUMBER = 26110501

# Les 4 actifs proposés dans l'interface (noms "de base", sans suffixe Exness)
SYMBOLES_DISPONIBLES = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

# Plafonds imposés : même si l'utilisateur saisit plus, on ramène à ces valeurs.
RISQUE_PAR_TRADE_MAX = 2.0      # % du capital par trade
PERTE_JOUR_MAX = 10.0           # % du capital par jour
TRADES_JOUR_MAX = 20            # nombre de trades par jour
POSITIONS_TOTAL_MAX = 4         # positions ouvertes en même temps (tous symboles)
POSITIONS_PAR_SYMBOLE = 1       # fixé : une seule position par symbole
# Mode "montants fixes" : plafond de la perte d'UN trade, en % du capital.
# (Remplace le plafond de 2 % tant que ce mode est actif.)
RISQUE_FIXE_MAX_PCT = 3.0

# Texte que l'utilisateur doit taper pour activer le mode réel
TEXTE_CONFIRMATION_REEL = "JE COMPRENDS LES RISQUES"


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
def data_dir() -> Path:
    """Dossier des données utilisateur : %APPDATA%\\MonBot sous Windows.

    Hors Windows (par exemple pour les tests automatiques), on utilise
    ~/.monbot afin que le code fonctionne partout.
    """
    base = os.environ.get("APPDATA")
    dossier = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def resource_path(relatif: str) -> Path:
    """Chemin d'un fichier livré avec le programme (interface, icône...).

    Quand le programme est compilé par PyInstaller, les fichiers sont
    décompressés dans un dossier temporaire indiqué par sys._MEIPASS.
    En développement, on part du dossier du projet.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(__file__).resolve().parent.parent
    return Path(base) / relatif


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
def _symboles_par_defaut() -> dict:
    # EURUSD et GBPUSD activés par défaut (cahier des charges §4)
    return {"EURUSD": True, "GBPUSD": True, "USDJPY": False, "XAUUSD": False}


@dataclass
class Settings:
    """Tous les réglages modifiables depuis l'interface."""

    # --- Actifs et unité de temps ---
    symbols: dict = field(default_factory=_symboles_par_defaut)
    timeframe: str = "M5"                 # "M5" (défaut) ou "M1"

    # --- Gestion du risque ---
    risk_per_trade: float = 1.0           # % du capital risqué par trade
    daily_loss_max: float = 3.0           # % de perte du jour qui arrête le bot
    max_trades_per_day: int = 6           # trades maximum par jour
    pause_after_loss_min: int = 10        # pause (minutes) après un trade perdant
    max_total_positions: int = 2          # positions simultanées, tous symboles

    # --- Plage horaire (heure de Paris) ---
    session_start: str = "09:00"
    session_end: str = "18:00"

    # --- Paramètres de la stratégie ---
    trend_ema: int = 200                  # filtre de tendance : 50 ou 200
    rsi_buy_max: float = 75.0             # pas d'achat au-dessus
    rsi_sell_min: float = 25.0            # pas de vente en dessous
    atr_sl_mult: float = 1.5              # stop loss = ATR x ce multiplicateur
    reward_risk: float = 1.2              # take profit = stop loss x ce ratio (>= 1)
    spread_factor_max: float = 2.0        # spread refusé s'il dépasse X fois la normale

    # --- Mode "montants fixes" (en devise du compte, ex. dollars) ---
    # Le TP et le SL de chaque trade sont posés pour gagner / perdre ces montants.
    fixed_money_mode: bool = True
    fixed_tp_money: float = 0.50          # gain visé par trade
    fixed_sl_money: float = 0.70          # perte maximale par trade

    # --- Pause "annonces économiques" (manuelle) ---
    news_pause_min: int = 30

    # --- Mode réel (désactivé par défaut) ---
    real_mode_enabled: bool = False

    # --- Interface ---
    theme: str = "dark"                   # "dark" ou "light"

    # --- Connexion MT5 (PAS de mot de passe ici !) ---
    mt5_login: str = ""
    mt5_server: str = ""
    mt5_path: str = ""                    # chemin de terminal64.exe (optionnel)
    remember_credentials: bool = False

    # -----------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Construit des réglages à partir d'un dictionnaire (fichier ou interface).

        Les clés inconnues sont ignorées, les valeurs manquantes prennent
        la valeur par défaut, puis tout est vérifié par validate().
        """
        s = cls()
        noms = {f.name for f in fields(cls)}
        for cle, valeur in (data or {}).items():
            if cle in noms:
                setattr(s, cle, valeur)
        s.validate()
        return s

    def validate(self) -> list[str]:
        """Corrige les valeurs hors limites. Renvoie la liste des corrections."""
        notes: list[str] = []

        def borne(nom, mini, maxi, typ=float):
            brut = getattr(self, nom)
            defaut = getattr(Settings(), nom)
            try:
                v = typ(brut)
            except (TypeError, ValueError):
                notes.append(f"{nom} : valeur invalide, remise à {defaut}")
                setattr(self, nom, defaut)
                return
            if v < mini or v > maxi:
                v2 = min(max(v, mini), maxi)
                notes.append(f"{nom} : {v} ramené à {v2} (autorisé : {mini} à {maxi})")
                v = v2
            setattr(self, nom, v)

        borne("risk_per_trade", 0.1, RISQUE_PAR_TRADE_MAX)
        borne("daily_loss_max", 0.5, PERTE_JOUR_MAX)
        borne("max_trades_per_day", 1, TRADES_JOUR_MAX, int)
        borne("pause_after_loss_min", 0, 240, int)
        borne("max_total_positions", 1, POSITIONS_TOTAL_MAX, int)
        borne("rsi_buy_max", 50, 95)
        borne("rsi_sell_min", 5, 50)
        borne("atr_sl_mult", 0.5, 5.0)
        borne("reward_risk", 1.0, 5.0)          # ratio 1:1 minimum imposé
        borne("spread_factor_max", 1.2, 5.0)
        borne("news_pause_min", 5, 240, int)
        borne("fixed_tp_money", 0.05, 1000.0)
        borne("fixed_sl_money", 0.05, 1000.0)
        self.fixed_money_mode = bool(self.fixed_money_mode)

        if self.timeframe not in ("M1", "M5"):
            notes.append("timeframe : seules M1 et M5 sont permises, remis à M5")
            self.timeframe = "M5"
        if int(self.trend_ema) not in (50, 200):
            notes.append("trend_ema : 50 ou 200 seulement, remis à 200")
            self.trend_ema = 200
        self.trend_ema = int(self.trend_ema)
        if self.theme not in ("dark", "light"):
            self.theme = "dark"

        for nom in ("session_start", "session_end"):
            if parse_hhmm(getattr(self, nom)) is None:
                defaut = getattr(Settings(), nom)
                notes.append(f"{nom} : format HH:MM attendu, remis à {defaut}")
                setattr(self, nom, defaut)

        # Actifs : on garde uniquement les 4 symboles connus
        propre = _symboles_par_defaut()
        if isinstance(self.symbols, dict):
            for sym in SYMBOLES_DISPONIBLES:
                if sym in self.symbols:
                    propre[sym] = bool(self.symbols[sym])
        self.symbols = propre

        self.real_mode_enabled = bool(self.real_mode_enabled)
        self.remember_credentials = bool(self.remember_credentials)
        self.mt5_login = str(self.mt5_login or "").strip()
        self.mt5_server = str(self.mt5_server or "").strip()
        self.mt5_path = str(self.mt5_path or "").strip()
        if self.mt5_login and not self.mt5_login.isdigit():
            notes.append("mt5_login : le numéro de compte ne contient que des chiffres")
            self.mt5_login = ""
        return notes


def parse_hhmm(texte: str):
    """Transforme "09:30" en (9, 30). Renvoie None si le format est faux."""
    try:
        h, m = str(texte).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Lecture / écriture du fichier de configuration
# ---------------------------------------------------------------------------
class ConfigStore:
    """Charge et enregistre les réglages dans %APPDATA%\\MonBot\\config.json."""

    def __init__(self, dossier: Path | None = None):
        self.path = (dossier or data_dir()) / "config.json"
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return Settings.from_dict(data)
            except (OSError, ValueError):
                # Fichier abîmé : on repart des valeurs par défaut (sans planter)
                pass
        return Settings()

    def get(self) -> Settings:
        """Renvoie une COPIE des réglages (pour éviter les modifications croisées)."""
        with self._lock:
            return Settings.from_dict(self._settings.to_dict())

    def update(self, changements: dict) -> list[str]:
        """Applique des changements, valide, enregistre. Renvoie les corrections."""
        with self._lock:
            data = self._settings.to_dict()
            data.update(changements or {})
            nouveau = Settings()
            noms = {f.name for f in fields(Settings)}
            for k, v in data.items():
                if k in noms:
                    setattr(nouveau, k, v)
            notes = nouveau.validate()
            self._settings = nouveau
            self._save()
            return notes

    def _save(self) -> None:
        # Écriture "atomique" : on écrit un fichier temporaire puis on le
        # renomme, pour ne jamais laisser un fichier à moitié écrit.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._settings.to_dict(), indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# Mot de passe MT5 : Gestionnaire d'identifiants Windows
# ---------------------------------------------------------------------------
_SERVICE_KEYRING = "MonBot-MT5"


def _keyring():
    """Renvoie le module keyring configuré sur le coffre Windows, ou None."""
    try:
        import keyring
        if sys.platform == "win32":
            # On force le coffre Windows : dans un .exe PyInstaller, la
            # détection automatique des "backends" peut échouer.
            from keyring.backends.Windows import WinVaultKeyring
            keyring.set_keyring(WinVaultKeyring())
        return keyring
    except Exception:
        return None


def save_password(login: str, mot_de_passe: str) -> bool:
    kr = _keyring()
    if kr is None or not login:
        return False
    try:
        kr.set_password(_SERVICE_KEYRING, str(login), mot_de_passe)
        return True
    except Exception:
        return False


def load_password(login: str) -> str | None:
    kr = _keyring()
    if kr is None or not login:
        return None
    try:
        return kr.get_password(_SERVICE_KEYRING, str(login))
    except Exception:
        return None


def delete_password(login: str) -> None:
    kr = _keyring()
    if kr is None or not login:
        return
    try:
        kr.delete_password(_SERVICE_KEYRING, str(login))
    except Exception:
        pass
