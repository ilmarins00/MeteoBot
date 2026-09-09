"""Genera le 23 icone meteo SVG usate dal sito (docs/icons/).

Icone semplici in stile flat, disegnate componendo forme di base (sole,
nuvola, goccia, fiocco di neve, fulmine, banchi di nebbia) cosi' da avere
uno stile coerente tra tutte e 23 le condizioni richieste.
"""
import math
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'docs', 'icons')

SUN = '#FFB300'
SUN_RAY = '#FFC107'
CLOUD_LIGHT = '#B0BEC5'
CLOUD = '#90A4AE'
CLOUD_DARK = '#607D8B'
CLOUD_STORM = '#546E7A'
RAIN = '#2196F3'
SNOW = '#81D4FA'
LIGHTNING = '#FFD600'
LIGHTNING_EDGE = '#FB8C00'
FOG = '#B0BEC5'
FOG_LIGHT = '#CFD8DC'


def sun(cx=50, cy=50, r=20, rays=True, color=SUN, ray_color=None, ray_frac=1.0):
    ray_color = ray_color or SUN_RAY
    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>']
    if rays:
        count = max(1, round(8 * ray_frac))
        for i in range(count):
            ang = i * (2 * math.pi / 8)
            x1 = cx + (r + 5) * math.cos(ang)
            y1 = cy + (r + 5) * math.sin(ang)
            x2 = cx + (r + 13) * math.cos(ang)
            y2 = cy + (r + 13) * math.sin(ang)
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'stroke="{ray_color}" stroke-width="4" stroke-linecap="round"/>')
    return '\n'.join(parts)


def cloud(cx, cy, w=1.0, color=CLOUD):
    s = w
    return '\n'.join([
        f'<ellipse cx="{cx}" cy="{cy + 10 * s:.1f}" rx="{34 * s:.1f}" ry="{18 * s:.1f}" fill="{color}"/>',
        f'<circle cx="{cx - 20 * s:.1f}" cy="{cy + 2 * s:.1f}" r="{16 * s:.1f}" fill="{color}"/>',
        f'<circle cx="{cx + 2 * s:.1f}" cy="{cy - 8 * s:.1f}" r="{22 * s:.1f}" fill="{color}"/>',
        f'<circle cx="{cx + 24 * s:.1f}" cy="{cy:.1f}" r="{15 * s:.1f}" fill="{color}"/>',
    ])


def raindrop(x, y, s=1.0, color=RAIN):
    return (f'<path d="M{x} {y} C{x - 7 * s:.1f} {y + 10 * s:.1f} {x - 7 * s:.1f} {y + 18 * s:.1f} '
            f'{x} {y + 22 * s:.1f} C{x + 7 * s:.1f} {y + 18 * s:.1f} {x + 7 * s:.1f} {y + 10 * s:.1f} '
            f'{x} {y} Z" fill="{color}"/>')


def snowflake(x, y, s=1.0, color=SNOW):
    lines = []
    length = 9 * s
    for i in range(3):
        ang = i * math.pi / 3
        x1 = x - length * math.cos(ang)
        y1 = y - length * math.sin(ang)
        x2 = x + length * math.cos(ang)
        y2 = y + length * math.sin(ang)
        lines.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="{color}" stroke-width="{2.4 * s:.1f}" stroke-linecap="round"/>')
        for ex, ey in ((x1, y1), (x2, y2)):
            tang = ang + math.pi / 2
            tl = 3.2 * s
            tx1, ty1 = ex - tl * math.cos(tang), ey - tl * math.sin(tang)
            tx2, ty2 = ex + tl * math.cos(tang), ey + tl * math.sin(tang)
            lines.append(f'<line x1="{tx1:.1f}" y1="{ty1:.1f}" x2="{tx2:.1f}" y2="{ty2:.1f}" '
                         f'stroke="{color}" stroke-width="{1.6 * s:.1f}" stroke-linecap="round"/>')
    return '\n'.join(lines)


def lightning(x, y, s=1.0):
    pts = (f'{x + 4 * s:.1f},{y:.1f} {x - 7 * s:.1f},{y + 17 * s:.1f} {x + 1 * s:.1f},{y + 17 * s:.1f} '
           f'{x - 5 * s:.1f},{y + 36 * s:.1f} {x + 10 * s:.1f},{y + 14 * s:.1f} {x + 1 * s:.1f},{y + 14 * s:.1f}')
    return f'<polygon points="{pts}" fill="{LIGHTNING}" stroke="{LIGHTNING_EDGE}" stroke-width="1"/>'


def fog_lines(cx, top, widths, gap=10, color=FOG, height=6, opacity=1.0):
    parts = []
    y = top
    for wd in widths:
        parts.append(f'<rect x="{cx - wd / 2:.1f}" y="{y}" width="{wd}" height="{height}" rx="{height / 2}" '
                     f'fill="{color}" opacity="{opacity}"/>')
        y += gap
    return '\n'.join(parts)


def moon(cx=50, cy=50, r=20, color='#CFD8DC', mask_id='moonMask'):
    """Luna a falce: cerchio pieno con un cerchio 'ritagliato' via mask, cosi'
    non dipende dal colore di sfondo dietro l'icona."""
    cutout_dx = r * 0.55
    cutout_dy = -r * 0.22
    cutout_r = r * 0.92
    return '\n'.join([
        f'<mask id="{mask_id}"><rect x="0" y="0" width="100" height="100" fill="#FFFFFF"/>'
        f'<circle cx="{cx + cutout_dx:.1f}" cy="{cy + cutout_dy:.1f}" r="{cutout_r:.1f}" fill="#000000"/></mask>',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" mask="url(#{mask_id})"/>',
        f'<circle cx="{cx - r - 6:.1f}" cy="{cy - r + 2:.1f}" r="1.6" fill="#FFFFFF" opacity="0.85"/>',
        f'<circle cx="{cx - r - 14:.1f}" cy="{cy - r + 10:.1f}" r="1.1" fill="#FFFFFF" opacity="0.7"/>',
    ])


def wrap(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">\n{body}\n</svg>\n'


ICONS = {}

ICONS['sereno'] = wrap(sun(50, 52, 24))

ICONS['prevalentemente-sereno'] = wrap('\n'.join([
    sun(40, 40, 20),
    cloud(64, 68, 0.55, CLOUD_LIGHT),
]))

ICONS['variabile'] = wrap('\n'.join([
    sun(36, 38, 19),
    cloud(58, 62, 0.8, CLOUD),
]))

ICONS['nubi-sparse'] = wrap('\n'.join([
    sun(50, 44, 16),
    cloud(24, 78, 0.42, CLOUD_LIGHT),
    cloud(80, 26, 0.36, CLOUD_LIGHT),
]))

ICONS['prevalentemente-coperto'] = wrap('\n'.join([
    sun(30, 32, 14),
    cloud(58, 62, 1.05, CLOUD_DARK),
]))

ICONS['coperto'] = wrap(cloud(50, 55, 1.3, CLOUD_DARK))

ICONS['nubi-alte-lievi'] = wrap('\n'.join([
    sun(50, 46, 22),
    fog_lines(50, 60, [26, 32, 22], gap=8, color='#FFFFFF', height=5, opacity=0.55),
]))

ICONS['nubi-alte'] = wrap('\n'.join([
    sun(50, 46, 22, ray_color='#FFE082'),
    fog_lines(50, 32, [50, 58, 44, 36], gap=9, color='#FFFFFF', height=6, opacity=0.72),
]))

ICONS['pioggia-debole'] = wrap('\n'.join([
    cloud(50, 40, 1.0, CLOUD),
    raindrop(50, 72, 1.0),
]))

ICONS['pioggia'] = wrap('\n'.join([
    cloud(50, 38, 1.0, CLOUD),
    raindrop(38, 70, 1.0),
    raindrop(62, 70, 1.0),
]))

ICONS['pioggia-forte'] = wrap('\n'.join([
    cloud(50, 36, 1.05, CLOUD_DARK),
    raindrop(32, 68, 1.0),
    raindrop(50, 74, 1.0),
    raindrop(68, 68, 1.0),
]))

ICONS['nubifragio'] = wrap('\n'.join([
    cloud(50, 32, 1.15, CLOUD_STORM),
    raindrop(22, 64, 0.85),
    raindrop(38, 72, 0.85),
    raindrop(50, 76, 0.85),
    raindrop(62, 72, 0.85),
    raindrop(78, 64, 0.85),
]))

ICONS['rovesci'] = wrap('\n'.join([
    cloud(50, 38, 1.0, CLOUD),
    raindrop(40, 70, 1.3),
    raindrop(64, 66, 0.7),
]))

ICONS['temporali'] = wrap('\n'.join([
    cloud(50, 34, 1.05, CLOUD_DARK),
    raindrop(34, 68, 0.9),
    raindrop(64, 68, 0.9),
    lightning(50, 58),
]))

ICONS['temporali-forti'] = wrap('\n'.join([
    cloud(50, 30, 1.15, CLOUD_STORM),
    raindrop(26, 66, 0.9),
    raindrop(50, 72, 0.9),
    raindrop(74, 66, 0.9),
    lightning(50, 54, 1.1),
]))

ICONS['nevischio'] = wrap('\n'.join([
    cloud(50, 40, 1.0, CLOUD_LIGHT),
    snowflake(50, 76, 0.85),
]))

ICONS['neve'] = wrap('\n'.join([
    cloud(50, 38, 1.0, CLOUD),
    snowflake(38, 76, 1.0),
    snowflake(62, 76, 1.0),
]))

ICONS['neve-forte'] = wrap('\n'.join([
    cloud(50, 34, 1.1, CLOUD),
    snowflake(30, 74, 1.0),
    snowflake(50, 80, 1.0),
    snowflake(70, 74, 1.0),
]))

ICONS['temporale-nevoso'] = wrap('\n'.join([
    cloud(50, 30, 1.15, CLOUD_STORM),
    snowflake(30, 70, 0.9),
    snowflake(50, 76, 0.9),
    snowflake(70, 70, 0.9),
    lightning(50, 54, 1.0),
]))

ICONS['pioggia-mista-neve'] = wrap('\n'.join([
    cloud(50, 38, 1.0, CLOUD),
    raindrop(38, 70, 1.0),
    snowflake(64, 76, 0.95),
]))

ICONS['nebbia'] = wrap(fog_lines(50, 30, [70, 82, 60, 76, 56], gap=11, color=FOG))

ICONS['nebbia-banchi'] = wrap('\n'.join([
    sun(50, 40, 20),
    fog_lines(50, 56, [58, 70, 46], gap=10, color=FOG_LIGHT, height=7),
]))

ICONS['foschia'] = wrap('\n'.join([
    sun(50, 42, 20),
    fog_lines(50, 68, [34, 40, 28], gap=7, color='#CFD8DC', height=3.5, opacity=0.85),
]))

# ── Varianti notturne (luna al posto del sole) per le condizioni dove il sole
# puo' comparire: usate di notte in base a orario di alba/tramonto (vedi app.js).
ICONS['sereno-notte'] = wrap(moon(50, 52, 24))

ICONS['prevalentemente-sereno-notte'] = wrap('\n'.join([
    moon(40, 40, 20),
    cloud(64, 68, 0.55, CLOUD_LIGHT),
]))

ICONS['variabile-notte'] = wrap('\n'.join([
    moon(36, 38, 19),
    cloud(58, 62, 0.8, CLOUD),
]))

ICONS['nubi-sparse-notte'] = wrap('\n'.join([
    moon(50, 44, 16),
    cloud(24, 78, 0.42, CLOUD_LIGHT),
    cloud(80, 26, 0.36, CLOUD_LIGHT),
]))

ICONS['prevalentemente-coperto-notte'] = wrap('\n'.join([
    moon(30, 32, 14),
    cloud(58, 62, 1.05, CLOUD_DARK),
]))

ICONS['nubi-alte-lievi-notte'] = wrap('\n'.join([
    moon(50, 46, 22),
    fog_lines(50, 60, [26, 32, 22], gap=8, color='#FFFFFF', height=5, opacity=0.4),
]))

ICONS['nubi-alte-notte'] = wrap('\n'.join([
    moon(50, 46, 22),
    fog_lines(50, 32, [50, 58, 44, 36], gap=9, color='#FFFFFF', height=6, opacity=0.55),
]))

ICONS['nebbia-banchi-notte'] = wrap('\n'.join([
    moon(50, 40, 20),
    fog_lines(50, 56, [58, 70, 46], gap=10, color=FOG_LIGHT, height=7),
]))

ICONS['foschia-notte'] = wrap('\n'.join([
    moon(50, 42, 20),
    fog_lines(50, 68, [34, 40, 28], gap=7, color='#CFD8DC', height=3.5, opacity=0.85),
]))

LABELS = {
    'sereno': 'Sereno',
    'prevalentemente-sereno': 'Prevalentemente sereno',
    'variabile': 'Variabile',
    'nubi-sparse': 'Nubi sparse',
    'prevalentemente-coperto': 'Prevalentemente coperto',
    'coperto': 'Coperto',
    'nubi-alte-lievi': 'Nubi alte lievi',
    'nubi-alte': 'Nubi alte',
    'pioggia-debole': 'Pioggia debole',
    'pioggia': 'Pioggia',
    'pioggia-forte': 'Pioggia forte',
    'nubifragio': 'Nubifragio',
    'rovesci': 'Rovesci',
    'temporali': 'Temporali',
    'temporali-forti': 'Temporali forti',
    'nevischio': 'Nevischio',
    'neve': 'Neve',
    'neve-forte': 'Neve forte',
    'temporale-nevoso': 'Temporale nevoso',
    'pioggia-mista-neve': 'Pioggia mista a neve',
    'nebbia': 'Nebbia',
    'nebbia-banchi': 'Nebbia a banchi',
    'foschia': 'Foschia',
}

if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    for key, svg in ICONS.items():
        path = os.path.join(OUT_DIR, f'wx-{key}.svg')
        with open(path, 'w') as f:
            f.write(svg)
    print(f'Generate {len(ICONS)} icone in {OUT_DIR}')
    missing = set(LABELS) - set(ICONS)
    if missing:
        print('ATTENZIONE, label senza icona:', missing)
