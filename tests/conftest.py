"""Permet à pytest de trouver le dossier bot/ (racine du projet)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
