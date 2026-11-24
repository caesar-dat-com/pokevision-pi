"""Augmentaciones y utilidades de dataset compartidas por los modelos de vision.

Todo el proyecto parte de las imagenes oficiales de TCGdex (data/images/*.webp).
De ahi derivamos, de forma reproducible:

  * vistas "fotografiadas" de la MISMA carta  -> entrenar el embedder (metric learning)
  * cartas "falsas" sinteticas                -> artefactos tipicos de falsificacion
  * cartas "danadas" sinteticas               -> desgaste fisico

Las clases negativas son SINTETICAS y esta documentado: no existe un dataset publico
etiquetado de falsificaciones. Las transformaciones replican los indicios que los
coleccionistas usan para detectar una falsa (color desviado, texto blando, bordes
mal cortados, holo plano) y el desgaste real de una carta jugada.
"""
from __future__ import annotations

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

CARD_W, CARD_H = 160, 224  # proporcion real de una carta (63x88mm ~ 0.716)


# --------------------------------------------------------------------------- utils
def load_card(path: str, size=(CARD_W, CARD_H)) -> Image.Image:
    im = Image.open(path).convert("RGB")
    return im.resize(size, Image.LANCZOS)


def _perspective_coeffs(src, dst):
    m = []
    for (x, y), (u, v) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.array(m, dtype=np.float64)
    B = np.array(src, dtype=np.float64).reshape(8)
    res = np.linalg.solve(A, B)
    return res.tolist()


def random_perspective(im: Image.Image, strength=0.06, rng=random) -> Image.Image:
    w, h = im.size
    d = strength
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [
        (rng.uniform(0, d) * w, rng.uniform(0, d) * h),
        (w - rng.uniform(0, d) * w, rng.uniform(0, d) * h),
        (w - rng.uniform(0, d) * w, h - rng.uniform(0, d) * h),
        (rng.uniform(0, d) * w, h - rng.uniform(0, d) * h),
    ]
    try:
        coeffs = _perspective_coeffs(src, dst)
    except Exception:  # noqa: BLE001
        return im
    return im.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def add_glare(im: Image.Image, rng=random, intensity=None) -> Image.Image:
    """Reflejo tipo holografica / luz de bombillo."""
    w, h = im.size
    inten = intensity if intensity is not None else rng.uniform(0.10, 0.40)
    glare = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(glare)
    cx, cy = rng.uniform(0, w), rng.uniform(0, h)
    rad = rng.uniform(0.3, 0.9) * max(w, h)
    ang = rng.uniform(0, math.pi)
    for i in range(14):
        f = 1 - i / 14
        rx, ry = rad * f, rad * f * rng.uniform(0.25, 0.6)
        box = [cx - rx, cy - ry, cx + rx, cy + ry]
        dr.ellipse(box, fill=int(255 * f * 0.5))
    glare = glare.rotate(math.degrees(ang), resample=Image.BICUBIC)
    glare = glare.filter(ImageFilter.GaussianBlur(radius=max(w, h) * 0.06))
    white = Image.new("RGB", (w, h), (255, 255, 255))
    return Image.composite(
        Image.blend(im, white, inten), im, glare.point(lambda v: int(v * 0.9))
    )


def photo_augment(im: Image.Image, rng=random) -> Image.Image:
    """Simula una foto de la carta tomada con la camara de la Raspberry."""
    im = random_perspective(im, strength=rng.uniform(0.01, 0.07), rng=rng)
    im = im.rotate(rng.uniform(-6, 6), resample=Image.BICUBIC, fillcolor=(18, 18, 22))
    if rng.random() < 0.8:
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.70, 1.30))
    if rng.random() < 0.8:
        im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.75, 1.25))
    if rng.random() < 0.6:
        im = ImageEnhance.Color(im).enhance(rng.uniform(0.80, 1.20))
    if rng.random() < 0.5:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.2)))
    if rng.random() < 0.5:
        im = add_glare(im, rng)
    if rng.random() < 0.7:  # ruido de sensor
        a = np.asarray(im).astype(np.float32)
        a += np.random.normal(0, rng.uniform(2, 9), a.shape)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < 0.3:  # recorte ligeramente descuadrado
        w, h = im.size
        dx, dy = int(w * rng.uniform(0, 0.05)), int(h * rng.uniform(0, 0.05))
        im = im.crop((dx, dy, w - dx, h - dy)).resize((w, h), Image.BICUBIC)
    return im


# ------------------------------------------------------------------ clases negativas
def make_fake(im: Image.Image, rng=random) -> Image.Image:
    """Artefactos tipicos de una carta falsificada (impresion barata)."""
    w, h = im.size
    n = rng.randint(2, 4)
    ops = rng.sample(
        ["color", "halftone", "soft_text", "bad_cut", "flat_holo", "gamma", "resample"], n
    )
    for op in ops:
        if op == "color":  # tintes desviados: las falsas salen frias o chillonas
            a = np.asarray(im).astype(np.float32)
            ch = rng.randint(0, 2)
            a[..., ch] *= rng.uniform(1.08, 1.30)
            a[..., (ch + 1) % 3] *= rng.uniform(0.80, 0.95)
            im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
            im = ImageEnhance.Color(im).enhance(rng.uniform(1.15, 1.6))
        elif op == "halftone":  # trama de impresion gruesa visible
            a = np.asarray(im).astype(np.float32)
            yy, xx = np.mgrid[0:h, 0:w]
            per = rng.choice([2, 3, 4])
            grid = ((xx % per == 0) | (yy % per == 0)).astype(np.float32)
            a *= 1 - grid[..., None] * rng.uniform(0.07, 0.18)
            im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        elif op == "soft_text":  # tipografia sin filo
            im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.8)))
            im = ImageEnhance.Sharpness(im).enhance(rng.uniform(0.2, 0.6))
        elif op == "bad_cut":  # bordes mal troquelados / borde amarillo ausente
            d = ImageDraw.Draw(im)
            bw = rng.randint(2, 6)
            col = rng.choice([(250, 250, 245), (20, 20, 20), (235, 220, 120)])
            side = rng.randint(0, 3)
            if side == 0:
                d.rectangle([0, 0, w, bw], fill=col)
            elif side == 1:
                d.rectangle([0, h - bw, w, h], fill=col)
            elif side == 2:
                d.rectangle([0, 0, bw, h], fill=col)
            else:
                d.rectangle([w - bw, 0, w, h], fill=col)
        elif op == "flat_holo":  # holo impreso plano, sin brillo direccional
            im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.55, 0.78))
            im = Image.blend(im, Image.new("RGB", (w, h), (128, 128, 132)), 0.12)
        elif op == "gamma":
            a = np.asarray(im).astype(np.float32) / 255.0
            a = np.power(a, rng.uniform(0.70, 1.45))
            im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
        elif op == "resample":  # imagen sacada de internet y reimpresa
            s = rng.uniform(0.25, 0.5)
            small = im.resize((max(8, int(w * s)), max(8, int(h * s))), Image.BILINEAR)
            im = small.resize((w, h), Image.NEAREST)
    return im


def make_damaged(im: Image.Image, rng=random) -> Image.Image:
    """Desgaste fisico real: esquinas, rayones, dobleces, manchas, descoloramiento."""
    w, h = im.size
    im = im.copy()
    d = ImageDraw.Draw(im, "RGBA")
    n = rng.randint(2, 4)
    ops = rng.sample(
        ["corner", "scratch", "crease", "stain", "fade", "edge_wear", "bend"], n
    )
    for op in ops:
        if op == "corner":  # esquina blanqueada o doblada
            for _ in range(rng.randint(1, 3)):
                cx = rng.choice([0, w])
                cy = rng.choice([0, h])
                r = rng.randint(int(w * 0.06), int(w * 0.18))
                col = rng.choice([(250, 248, 240, 230), (200, 196, 188, 200)])
                d.pieslice([cx - r, cy - r, cx + r, cy + r], 0, 360, fill=col)
        elif op == "scratch":  # rayones finos claros
            for _ in range(rng.randint(3, 10)):
                x1, y1 = rng.uniform(0, w), rng.uniform(0, h)
                ln = rng.uniform(w * 0.1, w * 0.7)
                ang = rng.uniform(0, math.pi)
                x2, y2 = x1 + ln * math.cos(ang), y1 + ln * math.sin(ang)
                d.line([x1, y1, x2, y2], fill=(255, 255, 255, rng.randint(50, 130)),
                       width=rng.randint(1, 2))
        elif op == "crease":  # doblez marcado de lado a lado
            y = rng.uniform(h * 0.15, h * 0.85)
            d.line([0, y, w, y + rng.uniform(-10, 10)],
                   fill=(255, 255, 255, rng.randint(70, 150)), width=rng.randint(2, 4))
            d.line([0, y + 3, w, y + 3 + rng.uniform(-10, 10)],
                   fill=(0, 0, 0, rng.randint(40, 90)), width=rng.randint(1, 3))
        elif op == "stain":  # mancha de humedad / dedo
            for _ in range(rng.randint(1, 3)):
                cx, cy = rng.uniform(0, w), rng.uniform(0, h)
                r = rng.uniform(w * 0.05, w * 0.22)
                d.ellipse([cx - r, cy - r, cx + r, cy + r],
                          fill=(rng.randint(90, 160), rng.randint(70, 130),
                                rng.randint(40, 90), rng.randint(40, 90)))
        elif op == "fade":  # descolorida por el sol
            im = ImageEnhance.Color(im).enhance(rng.uniform(0.35, 0.70))
            im = Image.blend(im, Image.new("RGB", (w, h), (235, 228, 210)),
                             rng.uniform(0.08, 0.22))
            d = ImageDraw.Draw(im, "RGBA")
        elif op == "edge_wear":  # borde comido / blanqueado
            bw = rng.randint(2, 5)
            for i in range(0, w, 3):
                if rng.random() < 0.6:
                    d.line([i, 0, i, rng.randint(1, bw + 3)],
                           fill=(250, 248, 242, 220), width=2)
                if rng.random() < 0.6:
                    d.line([i, h, i, h - rng.randint(1, bw + 3)],
                           fill=(250, 248, 242, 220), width=2)
        elif op == "bend":  # sombra de carta doblada
            grad = Image.new("L", (w, h))
            gd = ImageDraw.Draw(grad)
            x0 = rng.uniform(w * 0.2, w * 0.8)
            for x in range(w):
                gd.line([x, 0, x, h], fill=int(120 * math.exp(-((x - x0) ** 2) / (2 * (w * 0.08) ** 2))))
            im = Image.composite(
                ImageEnhance.Brightness(im).enhance(0.65), im,
                grad.filter(ImageFilter.GaussianBlur(4)))
            d = ImageDraw.Draw(im, "RGBA")
    return im


def list_images(img_dir: str):
    return sorted(
        os.path.join(img_dir, f)
        for f in os.listdir(img_dir)
        if f.lower().endswith((".webp", ".png", ".jpg", ".jpeg"))
    )
