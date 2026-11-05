"""
main.py : point d'entrée de MonBot.

- Crée la fenêtre Windows native (pywebview + Edge WebView2) qui affiche
  l'interface du dossier ui/.
- NE se connecte PAS à MT5 ici : la connexion n'a lieu qu'au clic sur
  « Démarrer » (cahier des charges §3).
- Compilé avec PyInstaller en mode --windowed : aucune console visible.

Pour tester sans compiler (sur votre PC, après pip install -r requirements.txt) :
    python main.py
"""
from __future__ import annotations

import sys


def main() -> None:
    import webview  # pywebview

    from bot.api import Api
    from bot.config import APP_NAME, ConfigStore, data_dir, resource_path
    from bot.engine import TradingEngine
    from bot.journal import Journal

    dossier = data_dir()                 # %APPDATA%\MonBot
    store = ConfigStore(dossier)
    journal = Journal(dossier)
    engine = TradingEngine(store, journal)
    api = Api(store, journal, engine, dossier)
    journal.info(f"{APP_NAME} lancé. Mode démo par défaut. Cliquez sur « Démarrer » pour vous connecter à MT5.")

    theme = store.get().theme
    fenetre = webview.create_window(
        title=APP_NAME,
        url=str(resource_path("ui/index.html")),
        js_api=api,
        width=1360, height=900, min_size=(1024, 700),
        # Couleur affichée pendant le chargement (évite un flash blanc)
        background_color="#0b1020" if theme == "dark" else "#eef3fb",
    )

    def a_la_fermeture():
        # Arrête proprement le bot et se déconnecte de MT5.
        # Les positions ouvertes restent chez le broker avec leur SL/TP.
        try:
            engine.shutdown()
            journal.info("Logiciel fermé.")
            journal.close()
        except Exception:
            pass

    fenetre.events.closing += a_la_fermeture

    # storage_path : données du moteur WebView2 dans %APPDATA%\MonBot\webview
    # (jamais dans le dossier du programme).
    webview.start(debug=False, storage_path=str(dossier / "webview"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # dernier filet de sécurité : jamais de plantage muet
        try:
            import ctypes
            import traceback
            from bot.config import data_dir
            (data_dir() / "erreur_demarrage.txt").write_text(traceback.format_exc(), encoding="utf-8")
            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(
                    0, f"MonBot n'a pas pu démarrer :\n{exc}\n\nDétails dans "
                       f"%APPDATA%\\MonBot\\erreur_demarrage.txt", "MonBot", 0x10)
        finally:
            sys.exit(1)
