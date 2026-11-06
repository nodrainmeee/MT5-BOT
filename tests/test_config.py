"""Tests de la migration des anciens fichiers de réglages."""
import json
import tempfile
from pathlib import Path

from bot.config import ConfigStore


def _store(contenu: dict) -> tuple[ConfigStore, Path]:
    d = Path(tempfile.mkdtemp())
    (d / "config.json").write_text(json.dumps(contenu), encoding="utf-8")
    return ConfigStore(d), d


def test_ancien_fichier_prend_le_gain_fixe_010():
    # Ancien fichier (sans settings_version) avec l'ancien gain 0,50 et 2 positions max
    store, d = _store({"fixed_tp_money": 0.5, "fixed_sl_money": 0.7, "max_total_positions": 2,
                       "max_positions_per_symbol": 1})
    s = store.get()
    assert s.fixed_money_mode and s.fixed_tp_money == 0.10 and s.fixed_sl_money == 0.70
    assert s.max_positions_per_symbol == 3 and s.max_total_positions == 6
    # ... et le fichier est réécrit pour ne pas recommencer
    assert json.loads((d / "config.json").read_text(encoding="utf-8"))["settings_version"] == 2


def test_nouveau_fichier_garde_le_choix_de_l_utilisateur():
    store, _ = _store({"settings_version": 2, "fixed_tp_money": 0.30})
    assert store.get().fixed_tp_money == 0.30


def test_pas_de_fichier_defaut_010():
    s = ConfigStore(Path(tempfile.mkdtemp())).get()
    assert s.fixed_money_mode and s.fixed_tp_money == 0.10
