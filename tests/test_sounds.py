"""Tests des sons (avec un faux haut-parleur : aucun son réel n'est joué)."""
import io
import struct
import wave

from bot.config import Settings
from bot.sounds import MOTIFS, SoundPlayer, render_wav


def _crete(octets: bytes) -> int:
    with wave.open(io.BytesIO(octets)) as w:
        n = w.getnframes()
        return max(abs(v) for v in struct.unpack(f"<{n}h", w.readframes(n)))


def _lecteur(actif=True, volume=70, horloge=lambda: 0.0):
    joues = []
    return SoundPlayer(lambda: (actif, volume), joueur=joues.append, horloge=horloge), joues


def test_wav_valide_et_volume():
    octets = render_wav(MOTIFS["win"], 100)
    with wave.open(io.BytesIO(octets)) as w:
        duree_ms = w.getnframes() / w.getframerate() * 1000
    assert abs(duree_ms - sum(d for _, d in MOTIFS["win"])) < 5
    assert _crete(render_wav(MOTIFS["win"], 100)) > _crete(render_wav(MOTIFS["win"], 30)) > 0
    assert _crete(render_wav(MOTIFS["win"], 0)) == 0


def test_tous_les_motifs_sont_distincts():
    assert len({render_wav(m, 70) for m in MOTIFS.values()}) == len(MOTIFS)


def test_joue_un_son_quand_actif():
    p, joues = _lecteur()
    assert p.play("open") and p.play("win") and p.play("loss")
    p.attendre()
    assert len(joues) == 3


def test_silence_si_desactive_ou_volume_zero():
    for actif, volume in ((False, 70), (True, 0)):
        p, joues = _lecteur(actif, volume)
        assert not p.play("win")
        p.attendre()
        assert joues == []


def test_alerte_pas_repetee_en_boucle():
    t = [0.0]
    p, joues = _lecteur(horloge=lambda: t[0])
    assert p.play("alert")
    t[0] = 5.0
    assert not p.play("alert")            # moins de 20 s : ignorée
    t[0] = 25.0
    assert p.play("alert")
    p.attendre()
    assert len(joues) == 2


def test_sans_carte_son_pas_d_erreur():
    p = SoundPlayer(lambda: (True, 70), joueur=None)
    assert not p.available and not p.play("win") and not p.test()
    def casse(_): raise RuntimeError("pas de périphérique")
    p2 = SoundPlayer(lambda: (True, 70), joueur=casse)
    assert p2.play("win")
    p2.attendre()                         # l'erreur est avalée, le fil continue


def test_bouton_test_joue_tout_sans_bloquer():
    p, joues = _lecteur(actif=False)      # même désactivé, le test joue
    assert p.test(50)
    p.attendre()
    assert len(joues) == 12               # 6 sons + 6 silences


def test_reglages_sons():
    s = Settings.from_dict({"sound_volume": 500})
    assert s.sound_volume == 100 and s.sound_enabled
    assert Settings.from_dict({"sound_volume": -3}).sound_volume == 0
