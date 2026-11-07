"""Genera favicon.png con el logo de Pocket Price AI (las mismas tres franjas del logo SVG).
Uso: python generar_favicon.py  (requiere Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

ESCALA = 256 / 44  # el logo SVG mide 40x44
FRANJAS = [  # (polígono en coordenadas del SVG, color)
    ([(8, 2), (36, 2), (32, 14), (4, 14)], "#E8730C"),
    ([(6, 17), (30, 17), (26, 29), (2, 29)], "#F29A4A"),
    ([(4, 32), (16, 32), (12, 44), (0, 44)], "#E8730C"),
]

img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
dibujo = ImageDraw.Draw(img)
desplazamiento = (256 - 40 * ESCALA) / 2  # centrar horizontalmente
for puntos, color in FRANJAS:
    dibujo.polygon([(x * ESCALA + desplazamiento, y * ESCALA) for x, y in puntos], fill=color)
img.resize((64, 64), Image.LANCZOS).save(Path(__file__).parent / "favicon.png")
print("favicon.png generado")
