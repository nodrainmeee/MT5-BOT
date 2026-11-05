"""
make_icon.py : dessine l'icône de MonBot (assets/icon.ico) avec Pillow.

Pourquoi un script ? Un fichier .ico est un fichier binaire : impossible
de le "copier-coller" comme du texte. Ce script le fabrique
automatiquement pendant la compilation sur GitHub.
Vous pouvez aussi remplacer assets/icon.ico par votre propre icône (dans
ce cas, retirez l'étape "Création de l'icône" du workflow et la ligne
assets/icon.ico du .gitignore).

Utilisation : python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

TAILLE = 256
sortie = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
sortie.parent.mkdir(exist_ok=True)

img = Image.new("RGBA", (TAILLE, TAILLE), (0, 0, 0, 0))

# Fond : carré très arrondi avec un dégradé bleu -> vert
degrade = Image.new("RGBA", (TAILLE, TAILLE))
px = degrade.load()
for y in range(TAILLE):
    for x in range(TAILLE):
        t = (x + y) / (2 * TAILLE)
        px[x, y] = (int(37 + (16 - 37) * t), int(99 + (185 - 99) * t), int(235 + (129 - 235) * t), 255)
masque = Image.new("L", (TAILLE, TAILLE), 0)
ImageDraw.Draw(masque).rounded_rectangle([8, 8, TAILLE - 8, TAILLE - 8], radius=64, fill=255)
img.paste(degrade, (0, 0), masque)

d = ImageDraw.Draw(img)
# Reflet "verre" en haut
d.rounded_rectangle([20, 18, TAILLE - 20, 110], radius=50, fill=(255, 255, 255, 40))
# Courbe montante + point (même dessin que le logo de l'interface)
points = [(52, 180), (104, 128), (146, 156), (204, 84)]
d.line(points, fill=(255, 255, 255, 255), width=20, joint="curve")
for x, y in points[:-1]:
    d.ellipse([x - 10, y - 10, x + 10, y + 10], fill=(255, 255, 255, 255))
d.ellipse([186, 66, 222, 102], fill=(255, 255, 255, 255))

img.save(sortie, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"Icône créée : {sortie}")
