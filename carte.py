# -*- coding: utf-8 -*-
"""Carte des 47 provinces en SVG : contours, noms de toutes les provinces, bulle au survol.

Les noms sont places au centre de chaque province ; quand deux noms se chevauchent (petites provinces voisines),
le moins bien place est deplace dans un espace libre et relie a sa province par un petit trait.
"""
import re

import numpy as np

FS = 11.0                     # taille des noms (px dans le repere 800 x 586)
LARGEUR_CAR = 0.50            # largeur moyenne d'un caractere, en fraction de la taille


def _anneaux(path):
    out = []
    for morceau in re.split(r"(?=M)", path):
        pts = re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", morceau)
        if len(pts) > 2:
            out.append(np.array(pts, dtype=float))
    return out


def _centre(anneaux):
    """Centre de gravite du plus grand anneau (formule du polygone)."""
    meilleur, aire_max = None, 0.0
    for a in anneaux:
        x, y = a[:, 0], a[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        c = x * y1 - x1 * y
        aire = c.sum() / 2
        if abs(aire) > aire_max:
            aire_max = abs(aire)
            meilleur = (((x + x1) * c).sum() / (6 * aire), ((y + y1) * c).sum() / (6 * aire), aire_max)
    return meilleur


def positions_etiquettes(carte, noms):
    """{code: (x, y, x_ancre, y_ancre, deplace)} : position du texte et point d'ancrage dans la province."""
    ancres, tailles = {}, {}
    for code, geo in carte["provinces"].items():
        cx, cy, aire = _centre(_anneaux(geo["path"]))
        ancres[code] = np.array([cx, cy])
        tailles[code] = (len(noms[code]) * FS * LARGEUR_CAR, FS)
    codes = list(ancres)
    pos = {c: ancres[c].copy() for c in codes}

    def boite(c, p=None):
        p = pos[c] if p is None else p
        w, h = tailles[c]
        return p[0] - w / 2 - 1.5, p[1] - h / 2 - 1, p[0] + w / 2 + 1.5, p[1] + h / 2 + 1

    def recouvre(a, b):
        A, B = boite(a), boite(b)
        dx = min(A[2], B[2]) - max(A[0], B[0])
        dy = min(A[3], B[3]) - max(A[1], B[1])
        return (dx, dy) if dx > 0 and dy > 0 else None

    for _ in range(400):
        bouge = False
        for i, a in enumerate(codes):
            for b in codes[i + 1:]:
                r = recouvre(a, b)
                if r is None:
                    continue
                bouge = True
                dx, dy = r
                d = pos[a] - pos[b]
                if dy <= dx:                                  # separer plutot verticalement
                    s = np.sign(d[1]) or 1.0
                    pos[a][1] += s * (dy / 2 + 0.3)
                    pos[b][1] -= s * (dy / 2 + 0.3)
                else:
                    s = np.sign(d[0]) or 1.0
                    pos[a][0] += s * (dx / 2 + 0.3)
                    pos[b][0] -= s * (dx / 2 + 0.3)
        for c in codes:                                       # rester dans le cadre, et pres de sa province
            w, h = tailles[c]
            pos[c][0] = float(np.clip(pos[c][0], w / 2 + 2, carte["largeur"] - w / 2 - 2))
            pos[c][1] = float(np.clip(pos[c][1], h / 2 + 2, carte["hauteur"] - h / 2 - 2))
            pos[c] += 0.08 * (ancres[c] - pos[c])
        if not bouge:
            break
    return {c: (float(pos[c][0]), float(pos[c][1]), float(ancres[c][0]), float(ancres[c][1]),
                bool(np.hypot(*(pos[c] - ancres[c])) > 9)) for c in codes}


def contours_regions(carte, region_par_code, echelle=4):
    """Contour de chaque region = union de ses provinces, obtenu par une grille fine (matplotlib, PIL).

    Renvoie {region: {"path": "M...Z", "x": cx, "y": cy}} ; (x, y) est le centre de la region, pour son etiquette.
    """
    from PIL import Image, ImageDraw
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    L, H = int(carte["largeur"]), int(carte["hauteur"])
    par_region = {}
    for code, geo in carte["provinces"].items():
        par_region.setdefault(region_par_code[code], []).append(geo["path"])
    sortie = {}
    for region, chemins in par_region.items():
        img = Image.new("L", (L * echelle, H * echelle), 0)
        dessin = ImageDraw.Draw(img)
        for chemin in chemins:
            for anneau in _anneaux(chemin):
                dessin.polygon([(x * echelle, y * echelle) for x, y in anneau], fill=255)
        masque = np.array(img, dtype=float) / 255.0
        fig, ax = plt.subplots()
        segments = ax.contour(masque, levels=[0.5]).allsegs[0]
        plt.close(fig)
        morceaux = []
        for seg in segments:
            if len(seg) < 4:
                continue
            pts = np.round(seg / echelle, 1)
            morceaux.append("M" + "L".join(f"{x:g},{y:g}" for x, y in pts[::2]) + "Z")
        ys, xs = np.nonzero(masque > 0.5)
        sortie[region] = {"path": "".join(morceaux), "x": round(float(xs.mean()) / echelle, 1),
                          "y": round(float(ys.mean()) / echelle, 1)}
    return sortie
