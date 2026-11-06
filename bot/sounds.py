"""
sounds.py : sons du bot (ouverture, gain, perte, alerte...).

Les sons sont fabriqués par le logiciel lui-même (petites mélodies de notes) : aucun
fichier audio à installer. Sous Windows ils sont joués avec 'winsound' (inclus dans Python),
dans un fil séparé : le bot n'attend jamais la fin d'un son.

Sur un PC sans carte son / un serveur distant sans audio, rien ne se passe (pas d'erreur).
Ce module est testé automatiquement avec un faux "haut-parleur".
"""
from __future__ import annotations

import io
import math
import queue
import struct
import threading
import time
import wave

TAUX = 22050                      # échantillons par seconde (qualité suffisante pour des bips)

# Chaque son = liste de (fréquence en Hz, durée en ms). Fréquence 0 = silence.
MOTIFS = {
    "start": [(880, 150)],                                         # bot démarré
    "stop": [(600, 150)],                                          # bot arrêté
    "open": [(660, 90), (880, 130)],                               # position ouverte (2 notes qui montent)
    "win": [(660, 90), (880, 90), (1175, 170)],                    # position fermée en gain (3 notes qui montent)
    "loss": [(440, 180), (294, 280)],                              # position fermée en perte (2 notes qui descendent)
    "alert": [(523, 160), (0, 70), (523, 160), (0, 70), (523, 280)],   # erreur, arrêt du jour, urgence
}
PAUSE_MIN = {"alert": 20.0}        # secondes minimum entre deux sons du même type (évite le vacarme)
TEST_ORDRE = ("start", "open", "win", "loss", "alert", "stop")


def render_wav(motif, volume: int) -> bytes:
    """Fabrique un fichier WAV (en mémoire) pour un motif et un volume de 0 à 100."""
    amplitude = max(0, min(100, int(volume))) / 100.0 * 0.6 * 32767
    echantillons = []
    for freq, duree_ms in motif:
        n = int(TAUX * duree_ms / 1000)
        fondu = max(1, int(TAUX * 0.006))                 # fondu de 6 ms : évite les "clics"
        for i in range(n):
            if freq <= 0:
                echantillons.append(0)
                continue
            env = min(1.0, i / fondu, (n - 1 - i) / fondu)
            echantillons.append(int(amplitude * env * math.sin(2 * math.pi * freq * i / TAUX)))
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAUX)
        w.writeframes(struct.pack(f"<{len(echantillons)}h", *echantillons))
    return tampon.getvalue()


def joueur_windows():
    """Fonction qui joue des octets WAV (Windows), ou None si indisponible."""
    try:
        import winsound
    except ImportError:
        return None

    def jouer(donnees: bytes) -> None:
        winsound.PlaySound(donnees, winsound.SND_MEMORY)      # synchrone, dans notre fil

    return jouer


class SoundPlayer:
    def __init__(self, reglages, joueur="auto", horloge=time.monotonic):
        """reglages() -> (sons activés ?, volume 0-100). joueur : fonction(octets) ou None."""
        self._reglages = reglages
        self._joueur = joueur_windows() if joueur == "auto" else joueur
        self._horloge = horloge
        self._file: queue.Queue = queue.Queue()      # sans limite : la limite se vérifie dans play()
        self._dernier: dict = {}
        self._cache: dict = {}
        self._fil: threading.Thread | None = None
        self._verrou = threading.Lock()

    @property
    def available(self) -> bool:
        return self._joueur is not None

    def _octets(self, genre: str, volume: int) -> bytes:
        cle = (genre, volume)
        if cle not in self._cache:
            self._cache[cle] = render_wav(MOTIFS[genre], volume)
        return self._cache[cle]

    def _demarrer(self) -> None:
        with self._verrou:
            if self._fil is None or not self._fil.is_alive():
                self._fil = threading.Thread(target=self._boucle, name="MonBot-sons", daemon=True)
                self._fil.start()

    def _boucle(self) -> None:
        while True:
            donnees = self._file.get()
            try:
                if self._joueur:
                    self._joueur(donnees)
            except Exception:
                pass                       # pas de carte son, périphérique occupé... : on ignore
            finally:
                self._file.task_done()

    def play(self, genre: str, force: bool = False) -> bool:
        """Joue un son selon les réglages. Renvoie True s'il a été mis en file."""
        if genre not in MOTIFS or not self.available:
            return False
        try:
            actif, volume = self._reglages()
        except Exception:
            return False
        if not force and (not actif or int(volume) <= 0):
            return False
        maintenant = self._horloge()
        pause = PAUSE_MIN.get(genre, 0.0)
        if not force and pause and maintenant - self._dernier.get(genre, -1e9) < pause:
            return False
        self._dernier[genre] = maintenant
        if self._file.qsize() >= 8:
            return False                   # trop de sons en attente : on laisse tomber celui-ci
        self._file.put(self._octets(genre, int(volume)))
        self._demarrer()
        return True

    def test(self, volume: int | None = None) -> bool:
        """Joue tous les sons à la suite (bouton « Tester les sons »)."""
        if not self.available:
            return False
        if volume is None:
            volume = self._reglages()[1]
        for genre in TEST_ORDRE:
            self._file.put(self._octets(genre, int(volume)))
            self._file.put(self._octets("stop", 0))            # courte pause (silence) entre deux sons
        self._demarrer()
        return True

    def attendre(self) -> None:
        """Attend la fin des sons en cours (utilisé par les tests)."""
        self._file.join()
