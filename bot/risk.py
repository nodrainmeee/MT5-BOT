"""
risk.py : gestion du risque (cahier des charges §6).

Ce module est "pur" (aucun appel à MT5) : il reçoit des chiffres et
répond "oui/non + raison". Il est testé automatiquement sur GitHub.

Règles appliquées :
- taille de lot calculée à partir du risque (% du capital) et de la perte
  qu'occasionnerait 1 lot au stop loss ;
- respect du lot minimal, du pas de lot et du lot maximal du symbole ;
- REFUS du trade si même le lot minimal ferait risquer trop d'argent
  (cas très fréquent avec 30 $ sur un compte standard !) ;
- maximum de trades par jour, pause après une perte, perte maximale du
  jour (arrêt automatique), une position par symbole, total limité.
- Aucune martingale, aucune moyenne à la baisse : le lot ne dépend
  jamais des pertes précédentes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from .config import POSITIONS_PAR_SYMBOLE

# Tolérance : on accepte que le lot minimal dépasse le risque voulu de 10 %
# au maximum (arrondis), jamais plus.
TOLERANCE_LOT_MIN = 1.10


@dataclass
class LotResult:
    ok: bool
    volume: float = 0.0
    risk_amount: float = 0.0     # argent réellement risqué avec ce lot
    risk_pct: float = 0.0        # en % du capital
    reason: str = ""


def _decimales(pas: float) -> int:
    exp = Decimal(str(pas)).normalize().as_tuple().exponent
    return max(0, -int(exp))


def compute_lot(capital: float, risque_pct: float, perte_par_lot: float,
                lot_min: float, pas_lot: float, lot_max: float) -> LotResult:
    """Calcule le lot pour risquer 'risque_pct' % du capital.

    perte_par_lot = argent perdu (devise du compte) si 1 lot touche le stop loss.
    """
    if capital <= 0:
        return LotResult(False, reason="Capital nul ou négatif")
    if perte_par_lot <= 0 or math.isnan(perte_par_lot):
        return LotResult(False, reason="Impossible de calculer la valeur du pip")
    if pas_lot <= 0 or lot_min <= 0:
        return LotResult(False, reason="Caractéristiques de lot du symbole invalides")

    budget = capital * risque_pct / 100.0
    brut = budget / perte_par_lot
    # Arrondi VERS LE BAS au pas de lot (on ne risque jamais plus que prévu)
    nb_pas = math.floor(brut / pas_lot + 1e-9)
    volume = round(nb_pas * pas_lot, _decimales(pas_lot))
    if lot_max > 0:
        volume = min(volume, lot_max)

    if volume < lot_min:
        risque_min = lot_min * perte_par_lot
        if risque_min <= budget * TOLERANCE_LOT_MIN:
            volume = lot_min
        else:
            return LotResult(
                False, volume=0.0, risk_amount=risque_min,
                risk_pct=risque_min / capital * 100.0,
                reason=(f"Le lot minimal ({lot_min:g}) risquerait {risque_min:.2f} "
                        f"({risque_min / capital * 100:.1f} % du capital) au lieu de "
                        f"{budget:.2f} ({risque_pct:g} %). Trade refusé. "
                        "Astuce : compte Cent ou capital plus élevé."))

    risque = volume * perte_par_lot
    return LotResult(True, volume=volume, risk_amount=risque,
                     risk_pct=risque / capital * 100.0, reason="OK")


class RiskManager:
    """Garde en mémoire l'état du jour : trades, pertes, pauses, arrêt."""

    def __init__(self):
        self.day: date | None = None
        self.start_balance: float = 0.0     # solde au début de la journée
        self.realized_today: float = 0.0    # gains/pertes clôturés aujourd'hui (bot)
        self.trades_today: int = 0
        self.pause_until: datetime | None = None
        self.pause_reason: str = ""
        self.halted: bool = False           # True = perte max du jour atteinte
        self.halt_reason: str = ""

    # ---------------------------------------------------------------- journée
    def sync(self, aujourd_hui: date, solde: float, realise: float, nb_trades: int) -> bool:
        """Met à jour les chiffres du jour (lus dans l'historique MT5).

        Le solde de départ est recalculé ainsi : solde actuel - résultat
        réalisé du jour. Ainsi, même si le logiciel est relancé en cours de
        journée, les limites restent correctes. Renvoie True si nouveau jour.
        """
        nouveau_jour = self.day != aujourd_hui
        if nouveau_jour:
            self.day = aujourd_hui
            self.halted = False
            self.halt_reason = ""
            self.pause_until = None
            self.pause_reason = ""
        self.realized_today = float(realise)
        self.trades_today = max(int(nb_trades), self.trades_today if not nouveau_jour else 0)
        self.start_balance = float(solde) - self.realized_today
        return nouveau_jour

    def daily_pnl(self, flottant: float) -> float:
        return self.realized_today + float(flottant)

    def daily_pnl_pct(self, flottant: float) -> float:
        if self.start_balance <= 0:
            return 0.0
        return self.daily_pnl(flottant) / self.start_balance * 100.0

    def check_daily_loss(self, flottant: float, perte_max_pct: float) -> bool:
        """Active l'arrêt si la perte du jour atteint la limite. Renvoie True si arrêt."""
        pct = self.daily_pnl_pct(flottant)
        if pct <= -abs(perte_max_pct):
            if not self.halted:
                self.halted = True
                self.halt_reason = (f"Perte maximale du jour atteinte ({pct:.2f} % "
                                    f"pour une limite de -{abs(perte_max_pct):g} %)")
            return True
        return False

    # ---------------------------------------------------------------- pauses
    def register_loss(self, maintenant: datetime, minutes: int) -> None:
        if minutes > 0:
            self.set_pause(maintenant, minutes, "pause après un trade perdant")

    def set_pause(self, maintenant: datetime, minutes: int, raison: str) -> None:
        fin = maintenant + timedelta(minutes=int(minutes))
        if self.pause_until is None or fin > self.pause_until:
            self.pause_until = fin
            self.pause_reason = raison

    def clear_pause(self) -> None:
        self.pause_until = None
        self.pause_reason = ""

    def is_paused(self, maintenant: datetime) -> bool:
        if self.pause_until is not None and maintenant >= self.pause_until:
            self.clear_pause()
        return self.pause_until is not None

    # ---------------------------------------------------------------- décision
    def can_open(self, symbole: str, maintenant: datetime, positions_par_symbole: dict,
                 total_positions: int, max_trades: int, max_total: int) -> tuple[bool, str]:
        """Peut-on ouvrir un nouveau trade ? Renvoie (oui/non, raison)."""
        if self.halted:
            return False, self.halt_reason or "Bot arrêté pour la journée"
        if self.is_paused(maintenant):
            return False, f"En pause jusqu'à {self.pause_until:%H:%M} ({self.pause_reason})"
        if self.trades_today >= int(max_trades):
            return False, f"Maximum de trades du jour atteint ({self.trades_today}/{max_trades})"
        if positions_par_symbole.get(symbole, 0) >= POSITIONS_PAR_SYMBOLE:
            return False, f"Une position est déjà ouverte sur {symbole}"
        if total_positions >= int(max_total):
            return False, f"Nombre maximal de positions simultanées atteint ({total_positions}/{max_total})"
        return True, "OK"
