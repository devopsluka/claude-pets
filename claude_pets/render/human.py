"""Human "legend" characters on the pet rig: hair, faces, outfits, and the
props of their signature moves.

A legend is still a ``Design`` — the colour slots just mean something else:
``fur`` is the outfit, ``belly`` the skin, ``extra`` the hair and ``accent``
the signature colour (gloves, chain, shirt print, bulb, lightning).

Everything here is a function taking the painter; ``creature.py`` imports
this module at its very end, once the shared drawing helpers exist.
"""

import math
import random

import cairo

from .color import INK, WHITE, darken, lighten, mix, outline_of, rgb, src
from .creature import GOLD, LW, SILVER, SILVER_D, TAU, blob, ellipse, heart_path, paint, rounded_rect, star_path, stroke, tube

LENS = rgb("#17131B")
WOOD = rgb("#8A6A4F")
COPPER = rgb("#C77B3B")
SHOE = rgb("#2A2630")


def bezier(pts, t):
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * pts[0][0] + b * pts[1][0] + c * pts[2][0] + d * pts[3][0],
            a * pts[0][1] + b * pts[1][1] + c * pts[2][1] + d * pts[3][1])


def cloud(cr, blobs, fill, line):
    """A fluffy mass: overlapping circles sharing one outline."""
    cr.new_path()
    for x, y, r in blobs:
        ellipse(cr, x, y, r, r)
    src(cr, line)
    cr.set_line_width(LW * 2)
    cr.stroke_preserve()
    src(cr, fill)
    cr.fill()


def bolt(cr, x0, y0, x1, y1, seed, color, alpha=1.0, width=1.0):
    """A jagged lightning bolt; ``seed`` picks the shape so it can flicker."""
    rng = random.Random(seed)
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    steps = max(3, int(length / 6))
    cr.new_path()
    cr.move_to(x0, y0)
    for i in range(1, steps):
        t = i / steps
        off = rng.uniform(-1, 1) * min(5.0, length * 0.22)
        cr.line_to(x0 + dx * t + nx * off, y0 + dy * t + ny * off)
    cr.line_to(x1, y1)
    cr.set_line_join(cairo.LINE_JOIN_MITER)
    path = cr.copy_path()
    src(cr, color, 0.55 * alpha)
    cr.set_line_width(3.4 * width)
    cr.stroke()
    cr.append_path(path)
    src(cr, WHITE, alpha)
    cr.set_line_width(1.2 * width)
    cr.stroke()
    cr.set_line_join(cairo.LINE_JOIN_ROUND)


# ----------------------------------------------------------------------------
# head
# ----------------------------------------------------------------------------

def hair_back(pt, f):
    """Hair that shows around the skull (drawn before the head)."""
    cr, k, pose = pt.cr, pt.k, pt.p
    kind = pt.spec.get("hair")
    rx, ry = pt.head_rx, pt.head_ry
    ox = -f * 1.5
    if kind == "wild":
        puff = 1.2 if pose.shock else 1.0
        blobs = ((-rx - 3.0, -1.0, 9.0), (-rx - 1.5, -12.0, 10.5), (-rx + 6.0, -ry - 0.5, 10.5),
                 (-7.0, -ry - 5.0, 10.0), (6.0, -ry - 5.5, 10.5), (rx - 6.0, -ry - 0.5, 10.5),
                 (rx + 1.5, -12.0, 10.5), (rx + 3.0, -1.0, 9.0))
        cloud(cr, [(x + ox, y, r * puff) for x, y, r in blobs], k.hair, k.hair_line)
    elif kind == "curly":
        blobs = ((-rx + 0.5, -6.0, 7.5), (-rx + 6.0, -ry + 3.5, 8.5), (-9.0, -ry - 1.0, 8.5),
                 (3.0, -ry - 2.0, 9.0), (rx - 8.0, -ry + 2.5, 8.5), (rx - 0.5, -6.0, 7.5))
        cloud(cr, [(x + ox, y, r) for x, y, r in blobs], k.hair, k.hair_line)
    elif kind in ("braids", "slick"):
        grow = 1.9 if kind == "braids" else 2.4
        cr.save()
        cr.rectangle(-60, -70, 120, 70 + (3 if kind == "braids" else -8))
        cr.clip()
        blob(cr, ox, 0, rx + grow, ry + grow, pt.head_kt, pt.head_kb)
        paint(cr, k.hair, k.hair_line)
        cr.restore()
    if pose.shock:
        spikes(pt, f)


def spikes(pt, f):
    """Hair standing on end (electrocuted)."""
    cr, k = pt.cr, pt.k
    rx, ry = pt.head_rx, pt.head_ry
    for i in range(9):
        a = math.radians(196 + i * 18.5)
        bx, by = math.cos(a) * rx * 0.86, math.sin(a) * ry * 0.86
        tx, ty = math.cos(a) * (rx + 13 + (i % 2) * 4), math.sin(a) * (ry + 13 + (i % 2) * 4)
        px, py = -math.sin(a) * 4.0, math.cos(a) * 4.0
        cr.new_path()
        cr.move_to(bx - px, by - py)
        cr.line_to(tx, ty)
        cr.line_to(bx + px, by + py)
        cr.close_path()
        paint(cr, k.hair, k.hair_line, lw=1.6)


def ears(pt, f):
    cr, k = pt.cr, pt.k
    for side in (-1, 1):
        ellipse(cr, side * (pt.head_rx - 0.6) - f * 1.5, 4.0, 4.4, 5.8)
        paint(cr, k.skin, k.skin_line)


def hair_cap(pt, f):
    """Hair on the scalp (drawn clipped to the head shape)."""
    cr, k = pt.cr, pt.k
    kind = pt.spec.get("hair")
    rx, ry = pt.head_rx, pt.head_ry
    ox = f * 2.5
    top = -ry - 4
    light = lighten(k.hair, 0.28)
    if kind in ("buzz", "braids"):
        buzz = kind == "buzz"
        line_y = -ry + (7.5 if buzz else 12.0)
        side_y = -9.0 if buzz else -2.0
        cr.new_path()
        cr.move_to(-rx - 3, side_y)
        cr.line_to(-rx - 3, top)
        cr.line_to(rx + 3, top)
        cr.line_to(rx + 3, side_y)
        cr.curve_to(rx - 4, -ry + (11 if buzz else 16), 11 + ox, line_y - 1.5, ox, line_y)
        cr.curve_to(-11 + ox, line_y - 1.5, -rx + 4, -ry + (11 if buzz else 16), -rx - 3, side_y)
        cr.close_path()
        paint(cr, k.hair, None, alpha=0.72 if buzz else 1.0)
        if kind == "braids":
            for x in (-13.0, -4.5, 4.5, 13.0):
                cr.new_path()
                cr.move_to(x + ox, line_y - 0.5 + abs(x) * 0.12)
                cr.curve_to(x * 1.02 + ox, -ry + 5, x * 0.9, -ry, x * 0.8, top)
                stroke(cr, light, 1.1, 0.8)
    elif kind == "slick":
        cr.new_path()
        cr.move_to(-rx - 3, -7)
        cr.line_to(-rx - 3, top)
        cr.line_to(rx + 3, top)
        cr.line_to(rx + 3, -7)
        cr.curve_to(rx - 5, -ry + 13, 12 + ox, -ry + 12.5, ox, -ry + 7.5)
        cr.curve_to(-12 + ox, -ry + 12.5, -rx + 5, -ry + 13, -rx - 3, -7)
        cr.close_path()
        paint(cr, k.hair)
        cr.new_path()
        cr.move_to(ox, -ry + 7.5)
        cr.line_to(ox * 0.6, top)
        stroke(cr, light, 1.1)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 6 + ox, -ry + 5)
            cr.curve_to(side * 12 + ox, -ry + 4, side * 17, -ry + 8, side * 20, -ry + 13)
            stroke(cr, light, 1.2, 0.5)
    elif kind in ("curly", "wild"):
        y = -ry + (12.5 if kind == "curly" else 9.0)
        dip = 3.6 if kind == "curly" else 2.2
        xs = (rx - 3, 14.0, 5.0, -5.0, -14.0, -rx + 3)
        cr.new_path()
        cr.move_to(-rx - 3, 3)
        cr.line_to(-rx - 3, top)
        cr.line_to(rx + 3, top)
        cr.line_to(rx + 3, 3)
        cr.curve_to(rx, -4, rx - 2, y + 1, xs[0] + ox, y)
        for i in range(1, len(xs)):
            x0, x1 = xs[i - 1] + ox, xs[i] + ox
            cr.curve_to(x0 - 2, y + dip, x1 + 2, y + dip, x1, y)
        cr.curve_to(-rx + 2, y + 1, -rx, -4, -rx - 3, 3)
        cr.close_path()
        paint(cr, k.hair)
        if kind == "curly":
            cr.new_path()
            cr.move_to(-8 + ox, y + 1)
            cr.curve_to(-9, -ry + 6, -8, -ry + 2, -6, top)
            stroke(cr, light, 1.1, 0.7)


def hair_front(pt, f):
    """Hair that hangs outside the head outline (drawn after the head)."""
    cr, k, pose = pt.cr, pt.k, pt.p
    kind = pt.spec.get("hair")
    rx, ry = pt.head_rx, pt.head_ry
    if kind == "braids":
        sway = pose.tail * 1.6
        for side in (-1, 1):
            x0, y0 = side * (rx - 1.5) - f * 1.5, -5.0
            pts = ((x0, y0), (x0 + side * 4.5, y0 + 9), (x0 + side * 3 + sway, y0 + 20),
                   (x0 + side * 1.5 + sway * 1.6, y0 + 29))
            tube(cr, pts, 4.6, k.hair, k.hair_line, lw=1.6)
            if not pt.flat:
                for i in range(1, 6):
                    px, py = bezier(pts, i / 6.0)
                    cr.new_path()
                    cr.move_to(px - 2.0, py - 0.8)
                    cr.line_to(px + 2.0, py + 0.8)
                    stroke(cr, lighten(k.hair, 0.3), 1.0, 0.8)
            ex, ey = pts[3]
            ellipse(cr, ex, ey + 1.8, 2.7, 2.7)
            paint(cr, GOLD, outline_of(GOLD), lw=1.2)
    elif kind == "wild" and not pt.flat:
        for i, (a, length) in enumerate(((205, 7), (238, 9), (270, 8), (302, 9), (335, 7))):
            ang = math.radians(a)
            bx, by = math.cos(ang) * (rx + 9), math.sin(ang) * (ry + 8) - 4
            cr.new_path()
            cr.move_to(bx, by)
            cr.curve_to(bx + math.cos(ang) * length * 0.5, by + math.sin(ang) * length * 0.5 - 2,
                        bx + math.cos(ang) * length, by + math.sin(ang) * length - 1,
                        bx + math.cos(ang) * length + (2 if i % 2 else -2), by + math.sin(ang) * length + 1)
            stroke(cr, k.hair_line, 1.3, 0.8)


def nose(pt, nx, ny):
    cr = pt.cr
    cr.new_path()
    cr.arc(nx, ny - 0.6, 1.9, 0.15 * math.pi, 0.95 * math.pi)
    stroke(cr, pt.k.skin_line, 1.5, 0.9)


def _mustache(cr, cx, cy, half, thick, droop, fill, line):
    cr.new_path()
    cr.move_to(cx, cy - thick * 0.45)
    cr.curve_to(cx + half * 0.4, cy - thick * 0.8, cx + half * 0.9, cy - thick * 0.3, cx + half, cy + droop)
    cr.curve_to(cx + half * 0.7, cy + thick * 0.55 + droop * 0.3, cx + half * 0.3, cy + thick * 0.5, cx, cy + thick * 0.2)
    cr.curve_to(cx - half * 0.3, cy + thick * 0.5, cx - half * 0.7, cy + thick * 0.55 + droop * 0.3, cx - half, cy + droop)
    cr.curve_to(cx - half * 0.9, cy - thick * 0.3, cx - half * 0.4, cy - thick * 0.8, cx, cy - thick * 0.45)
    cr.close_path()
    paint(cr, fill, line, lw=1.3)


def facial_hair(pt, nx, my):
    cr, k = pt.cr, pt.k
    kind = pt.spec.get("facial", "none")
    if kind == "mustache":
        _mustache(cr, nx, my - 2.2, 8.6, 3.8, 0.7, k.hair, k.hair_line)
    elif kind == "bushy":
        _mustache(cr, nx, my - 1.6, 10.5, 5.2, 2.4, k.hair, k.hair_line)
    elif kind in ("thin", "goatee"):
        lift = 1.6 if kind == "thin" else 0.2
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(nx, my - 2.7)
            cr.curve_to(nx + side * 2.5, my - 3.6, nx + side * 5.2, my - 3.0, nx + side * 7.0, my - 2.8 - lift)
            stroke(cr, k.hair, 1.9 if kind == "thin" else 1.5)
        if kind == "goatee":
            ellipse(cr, nx, my + 5.9, 2.9, 2.5)
            paint(cr, k.hair)


def shades(pt, f):
    """Dark glasses; special eyes show up as reflections on the lenses."""
    cr, pose = pt.cr, pt.p
    ey = pt.eye_y
    kind = pose.eye
    centers = [side * pt.eye_dx + f * 5.5 for side in (-1, 1)]
    cr.new_path()
    cr.move_to(centers[0] + 6.6, ey - 1.6)
    cr.line_to(centers[1] - 6.6, ey - 1.6)
    stroke(cr, LENS, 1.9)
    for side, cx in zip((-1, 1), centers):
        cr.new_path()
        cr.move_to(cx + side * 6.6, ey - 1.8)
        cr.line_to(side * (pt.head_rx - 1.0), ey - 0.6)
        stroke(cr, LENS, 1.7)
        rounded_rect(cr, cx - 6.8, ey - 4.8, 13.6, 9.8, 3.8)
        paint(cr, LENS, INK, lw=1.3)
        if kind == "heart":
            heart_path(cr, cx, ey + 0.4, 2.7)
            paint(cr, rgb("#FF5C8A"))
        elif kind == "sparkle":
            star_path(cr, cx, ey, 3.4, 1.2, 4, math.sin(pose.t * 5.0) * 0.3)
            paint(cr, WHITE)
        elif kind in ("x", "squeeze"):
            for d in (-1, 1):
                cr.new_path()
                cr.move_to(cx - 2.8, ey - 2.4 * d)
                cr.line_to(cx + 2.8, ey + 2.4 * d)
                stroke(cr, WHITE, 1.5)
        elif kind == "spiral":
            cr.new_path()
            for i in range(19):
                a = pose.t * 6.0 * side + 2.0 * TAU * i / 18
                r = 3.6 * i / 18
                (cr.move_to if i == 0 else cr.line_to)(cx + r * math.cos(a), ey + r * math.sin(a))
            stroke(cr, WHITE, 1.2)
        elif kind == "wide":
            ellipse(cr, cx, ey, 2.6, 2.6)
            stroke(cr, WHITE, 1.3)
        else:
            cr.new_path()
            cr.move_to(cx - 3.6, ey + 1.8)
            cr.line_to(cx - 0.4, ey - 2.6)
            stroke(cr, WHITE, 1.3, 0.55)


def tattoo(pt, f):
    cr, k = pt.cr, pt.k
    ex, ey = pt.eye_dx + f * 5.5, pt.eye_y
    ink = mix(k.skin, INK, 0.75)
    cr.new_path()
    cr.move_to(ex + 4.5, ey - 8.6)
    cr.curve_to(ex + 9.5, ey - 8.2, ex + 11.6, ey - 4.2, ex + 10.6, ey - 0.6)
    stroke(cr, ink, 1.8)
    cr.new_path()
    cr.move_to(ex + 10.9, ey + 2.0)
    cr.curve_to(ex + 11.0, ey + 6.0, ex + 8.0, ey + 8.6, ex + 4.6, ey + 8.3)
    stroke(cr, ink, 1.8)
    cr.new_path()
    cr.move_to(ex + 8.4, ey - 4.6)
    cr.line_to(ex + 12.8, ey - 6.4)
    stroke(cr, ink, 1.5)


# ----------------------------------------------------------------------------
# body
# ----------------------------------------------------------------------------

def body(pt):
    cr, k = pt.cr, pt.k
    outfit = pt.spec.get("outfit", "sweater")
    by, brx, bry = pt.body_cy, pt.body_rx, pt.body_ry
    bare = outfit == "boxer"
    base, line = (k.skin, k.skin_line) if bare else (k.fur, k.line)
    pt.body_path()
    if pt.flat:
        paint(cr, base, line)
        return
    cr.save()
    cr.clip()
    src(cr, base)
    cr.paint()
    neck = pt.head_cy + pt.head_ry - 1.0
    if outfit == "boxer":
        cr.new_path()
        cr.rectangle(-40, by + 2.6, 80, 40)
        paint(cr, k.fur)
        cr.new_path()
        cr.move_to(-40, by + 3.8)
        cr.line_to(40, by + 3.8)
        stroke(cr, WHITE, 2.8)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 1.8, by - 5.6)
            cr.curve_to(side * 4, by - 3.0, side * 9, by - 3.0, side * 11.5, by - 6.2)
            stroke(cr, k.skin_line, 1.3, 0.55)
    elif outfit == "hoodie":
        cr.new_path()
        cr.move_to(-9, by + 9.5)
        cr.curve_to(-7, by + 4.5, 7, by + 4.5, 9, by + 9.5)
        stroke(cr, k.line, 1.4, 0.7)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 3.4, neck + 0.5)
            cr.line_to(side * 3.9, neck + 8.0)
            stroke(cr, WHITE, 1.5)
        cr.new_path()
        cr.move_to(-9.5, neck + 0.5)
        cr.curve_to(-6.5, neck + 10, 6.5, neck + 10, 9.5, neck + 0.5)
        stroke(cr, outline_of(GOLD), 3.0)
        cr.new_path()
        cr.move_to(-9.5, neck + 0.5)
        cr.curve_to(-6.5, neck + 10, 6.5, neck + 10, 9.5, neck + 0.5)
        stroke(cr, GOLD, 1.6)
        ellipse(cr, 0, neck + 9.0, 2.9, 2.9)
        paint(cr, GOLD, outline_of(GOLD), lw=1.2)
    elif outfit == "shirt":
        for i, (x, y) in enumerate(((-12, -3), (-6, 4), (-13, 9), (0, 9), (7, 2), (13, -4), (12, 8), (5, 12),
                                    (-4, -2), (-9, 13))):
            cr.save()
            cr.translate(x, by + y)
            cr.rotate(0.6 + i)
            rounded_rect(cr, -1.5, -1.5, 3.0, 3.0, 0.6)
            cr.restore()
            paint(cr, k.accent, None, alpha=0.85)
        cr.new_path()
        cr.move_to(-6.2, neck - 2)
        cr.line_to(6.2, neck - 2)
        cr.line_to(0, neck + 9.0)
        cr.close_path()
        paint(cr, k.skin)
        for x, y in ((-1.6, 2.4), (1.5, 3.4), (0.0, 5.6)):
            cr.new_path()
            cr.arc(x, neck + y, 1.0, 0.2, 4.2)
            stroke(cr, k.hair, 0.9, 0.85)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 6.2, neck - 2)
            cr.line_to(side * 11.0, neck + 3.8)
            cr.line_to(side * 3.4, neck + 4.6)
            cr.close_path()
            paint(cr, lighten(k.fur, 0.25), k.line, lw=1.4)
        for y in (12.5, 17.0):
            ellipse(cr, 0, neck + y, 0.95, 0.95)
            paint(cr, k.line)
    elif outfit == "sweater":
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(0, neck + 3.8)
            cr.line_to(side * 6.6, neck - 1.2)
            cr.line_to(side * 8.2, neck + 4.2)
            cr.close_path()
            paint(cr, WHITE, k.line, lw=1.3)
        cr.new_path()
        cr.move_to(-10, neck + 2.5)
        cr.curve_to(-5.5, neck + 9, 5.5, neck + 9, 10, neck + 2.5)
        stroke(cr, darken(k.fur, 0.22), 2.2)
        cr.new_path()
        cr.move_to(-brx, by + bry - 4.6)
        cr.line_to(brx, by + bry - 4.6)
        stroke(cr, darken(k.fur, 0.22), 2.0)
    elif outfit == "suit":
        cr.new_path()
        cr.move_to(-6.6, neck - 2)
        cr.line_to(6.6, neck - 2)
        cr.line_to(0, neck + 12.5)
        cr.close_path()
        paint(cr, WHITE)
        cr.new_path()
        cr.move_to(-1.9, neck - 0.5)
        cr.line_to(1.9, neck - 0.5)
        cr.line_to(2.5, neck + 9.0)
        cr.line_to(0, neck + 12.0)
        cr.line_to(-2.5, neck + 9.0)
        cr.close_path()
        paint(cr, rgb("#8B1E2D"), rgb("#4A0F18"), lw=1.0)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 6.8, neck - 2)
            cr.line_to(side * 1.2, neck + 13.5)
            stroke(cr, lighten(k.fur, 0.3), 1.7)
        ellipse(cr, 0, neck + 17.0, 1.0, 1.0)
        paint(cr, lighten(k.fur, 0.35))
    cr.restore()
    pt.body_path()
    paint(cr, None, line)


def hand(pt, side, sx, sy, ex, ey):
    cr, k = pt.cr, pt.k
    if pt.spec.get("gloves"):
        ellipse(cr, ex, ey, 6.0, 5.7)
        paint(cr, k.accent, k.accent_line, lw=1.9)
        ellipse(cr, ex - side * 3.4, ey - 2.4, 2.5, 2.3)
        paint(cr, k.accent, k.accent_line, lw=1.4)
        if not pt.flat:
            dx, dy = ex - sx, ey - sy
            length = math.hypot(dx, dy) or 1.0
            ux, uy = dx / length, dy / length
            wx, wy = ex - ux * 5.2, ey - uy * 5.2
            cr.new_path()
            cr.move_to(wx - uy * 3.6, wy + ux * 3.6)
            cr.line_to(wx + uy * 3.6, wy - ux * 3.6)
            stroke(cr, WHITE, 1.7)
    else:
        ellipse(cr, ex, ey, 3.9, 3.9)
        paint(cr, k.skin, k.skin_line, lw=1.7)


# ----------------------------------------------------------------------------
# signature items and props
# ----------------------------------------------------------------------------

def _joint(cr, x, y, direction, t, glow):
    x1, y1 = x + direction * 8.5, y - 2.2
    tube(cr, ((x, y), (x1, y1)), 2.2, rgb("#F6F1E4"), rgb("#8E8676"), lw=0.9)
    ember = mix(rgb("#B5482A"), rgb("#FFB340"), max(0.0, min(1.0, glow)))
    if glow > 0.5:
        ellipse(cr, x1 + direction * 0.8, y1 - 0.2, 3.6, 3.6)
        paint(cr, rgb("#FF9A3C"), None, alpha=0.35)
    ellipse(cr, x1 + direction * 0.8, y1 - 0.2, 1.7, 1.7)
    paint(cr, ember)
    cr.new_path()
    cr.move_to(x1 + direction, y1 - 2)
    wob = math.sin(t * 2.3)
    cr.curve_to(x1 + direction * (3 + wob), y1 - 6, x1 - direction * (1 - wob), y1 - 9, x1 + direction * 2, y1 - 13)
    cr.curve_to(x1 + direction * (4 - wob), y1 - 16, x1 + direction * wob, y1 - 18, x1 + direction * 1.5, y1 - 21)
    stroke(cr, rgb("#DDD8E4"), 1.1, 0.5)


def _bulb(cr, x, y, lit, t):
    lit = max(0.0, min(1.0, lit))
    if lit > 0.05:
        ellipse(cr, x, y, 10.5, 10.5)
        paint(cr, GOLD, None, alpha=0.28 * lit)
        for i in range(8):
            a = i * TAU / 8 + t * 0.8
            r0, r1 = 10.5, 13.5 + 1.5 * math.sin(t * 9.0 + i)
            cr.new_path()
            cr.move_to(x + math.cos(a) * r0, y + math.sin(a) * r0)
            cr.line_to(x + math.cos(a) * r1, y + math.sin(a) * r1)
            stroke(cr, GOLD, 1.7, 0.9 * lit)
    rounded_rect(cr, x - 2.9, y + 5.2, 5.8, 4.6, 1.2)
    paint(cr, SILVER_D, rgb("#6E7686"), lw=1.2)
    ellipse(cr, x, y, 6.2, 6.6)
    paint(cr, mix(rgb("#FFF8DC"), rgb("#FFD84A"), lit), rgb("#8A6A1F"), lw=1.5)
    cr.new_path()
    cr.move_to(x - 2.2, y + 3.4)
    cr.line_to(x - 1.2, y - 0.8)
    cr.line_to(x, y + 1.2)
    cr.line_to(x + 1.2, y - 0.8)
    cr.line_to(x + 2.2, y + 3.4)
    stroke(cr, rgb("#8A6A1F"), 0.9, 0.9)


def _bills(cr, x, y, t):
    green = rgb("#5BBF7A")
    for i, rot in enumerate((-0.5, -0.1, 0.3)):
        cr.save()
        cr.translate(x, y)
        cr.rotate(rot + math.sin(t * 6.0 + i) * 0.05)
        rounded_rect(cr, -3.4, -11.5, 6.8, 11.5, 1.0)
        cr.restore()
        paint(cr, green, outline_of(green), lw=1.1)
    ellipse(cr, x + 1.2, y - 6.5, 1.5, 1.5)
    paint(cr, lighten(green, 0.45))


def _pigeon(cr, x, y, t):
    grey = rgb("#A9B0BD")
    bob = math.sin(t * 5.0) * 0.6
    ellipse(cr, x, y - 4.5, 6.6, 4.8)
    paint(cr, grey, outline_of(grey), lw=1.5)
    ellipse(cr, x + 5.0, y - 9.5 + bob, 3.5, 3.5)
    paint(cr, lighten(grey, 0.18), outline_of(grey), lw=1.4)
    cr.new_path()
    cr.move_to(x + 8.2, y - 9.6 + bob)
    cr.line_to(x + 11.0, y - 8.8 + bob)
    cr.line_to(x + 8.0, y - 8.0 + bob)
    cr.close_path()
    paint(cr, rgb("#FFB238"))
    ellipse(cr, x + 5.8, y - 10.2 + bob, 0.8, 0.8)
    paint(cr, INK)
    cr.new_path()
    cr.move_to(x - 4.0, y - 5.5)
    cr.curve_to(x - 1.0, y - 2.0, x + 3.0, y - 2.4, x + 4.0, y - 5.0)
    stroke(cr, outline_of(grey), 1.2)


def item(pt):
    """Small signature item in a hand, at the mouth or over the head."""
    cr, pose = pt.cr, pt.p
    name = pose.item
    if not name or pt.flat:
        return
    at = pose.item_at
    direction = 1.0
    if at == "mouth":
        x = pt.head_cx + pose.facing * 8.0 + 3.2
        y = pt.head_cy + pt.eye_y + 11.4
    elif at == "over":
        x = pt.head_cx
        y = pt.head_cy - pt.head_ry - (24.0 if pt.spec.get("hair") in ("wild", "curly") else 19.0)
    else:
        side = -1 if at == "hand_l" else 1
        x, y = pt.hands.get(side, (side * 20.0, pt.body_cy))
        direction = float(side)
    if name == "joint":
        _joint(cr, x, y, direction, pose.t, pose.item_glow)
    elif name == "bulb":
        _bulb(cr, x, y - (7.5 if at != "over" else 0.0), pose.item_glow, pose.t)
    elif name == "bills":
        _bills(cr, x, y - 2.5, pose.t)
    elif name == "pigeon":
        _pigeon(cr, x, y + (13.0 if at == "over" else 0.0), pose.t)


def mirror(pt):
    """A little mirror with white lines on it. ``prop_t`` 0..1 = how much is gone."""
    cr, pose = pt.cr, pt.p
    ellipse(cr, 0, -1.6, 16.5, 4.4)
    paint(cr, rgb("#CFE3F2"), rgb("#5B6B7A"), lw=1.7)
    cr.new_path()
    cr.arc(-6, -2.4, 6.0, math.pi * 1.1, math.pi * 1.5)
    stroke(cr, WHITE, 1.1, 0.7)
    left = 3 - int(max(0.0, min(0.999, pose.prop_t)) * 3)
    for i in range(3 - left, 3):
        x = -8.5 + i * 6.5
        for width, color in ((3.0, rgb("#8FA0AF")), (1.9, WHITE)):
            cr.new_path()
            cr.move_to(x, -0.9)
            cr.line_to(x + 4.6, -2.4)
            stroke(cr, color, width)


def belt(pt):
    """Champion's belt, worn round the waist."""
    cr = pt.cr
    if pt.flat:
        return
    y = pt.body_cy + 4.5
    pt.body_path()
    cr.save()
    cr.clip()
    cr.new_path()
    cr.rectangle(-40, y - 3.8, 80, 7.6)
    paint(cr, rgb("#2A2630"))
    for side in (-1, 1):
        ellipse(cr, side * 14.0, y, 2.6, 2.6)
        paint(cr, GOLD, outline_of(GOLD), lw=1.0)
    cr.restore()
    ellipse(cr, 0, y, 9.5, 6.8)
    paint(cr, GOLD, outline_of(GOLD), lw=1.8)
    ellipse(cr, 0, y, 5.8, 3.8)
    paint(cr, lighten(GOLD, 0.4), outline_of(GOLD), lw=1.0)
    ellipse(cr, 0, y, 1.9, 1.9)
    paint(cr, rgb("#E11D48"))


def chalkboard(pt, side):
    cr, pose = pt.cr, pt.p
    x = side * 48.0
    for dx in (-10, 10):
        cr.new_path()
        cr.move_to(x + dx * 0.8, -40)
        cr.line_to(x + dx * 1.25, 0)
        stroke(cr, WOOD, 2.4)
    rounded_rect(cr, x - 16, -68, 32, 26, 2.6)
    paint(cr, rgb("#2F5D50"), WOOD, lw=2.6)
    if pt.flat:
        return
    chalk = rgb("#F4F1E6")
    cr.select_font_face("Adwaita Sans", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(8.2)
    cr.move_to(x - 12.5, -57)
    src(cr, chalk, 0.95)
    cr.show_text("E=mc²")
    cr.new_path()
    shown = 1 + int(pose.prop_t * 1.4) % 3
    for i in range(shown):
        cr.new_path()
        cr.move_to(x - 12, -52 + i * 3.4)
        cr.curve_to(x - 6, -54 + i * 3.4, x, -50 + i * 3.4, x + 4 + (i * 4) % 9, -52 + i * 3.4)
        stroke(cr, chalk, 1.0, 0.75)


def coil(pt, side):
    """A small Tesla coil throwing sparks."""
    cr, pose, k = pt.cr, pt.p, pt.k
    x = side * 46.0
    rounded_rect(cr, x - 9.5, -9.5, 19, 9.5, 2.6)
    paint(cr, rgb("#3A3342"), INK, lw=1.8)
    rounded_rect(cr, x - 4.6, -35, 9.2, 26.5, 2.0)
    paint(cr, COPPER, outline_of(COPPER), lw=1.6)
    ellipse(cr, x, -38.5, 11.5, 5.2)
    paint(cr, SILVER, rgb("#6E7686"), lw=1.8)
    if pt.flat:
        return
    for i in range(7):
        cr.new_path()
        cr.move_to(x - 4.6, -32.5 + i * 3.5)
        cr.line_to(x + 4.6, -31.3 + i * 3.5)
        stroke(cr, darken(COPPER, 0.35), 1.0, 0.9)
    cr.new_path()
    cr.arc(x - 3, -40.0, 6.0, math.pi * 1.1, math.pi * 1.5)
    stroke(cr, WHITE, 1.2, 0.8)
    seed = int(pose.prop_t * 14.0)
    rng = random.Random(seed * 7919 + 13)
    for n in range(2 + seed % 2):
        a = rng.uniform(math.pi * 1.05, math.pi * 1.95) if n else (math.pi * (1.0 if side > 0 else 0.0) + rng.uniform(-0.5, 0.5))
        reach = rng.uniform(15, 25)
        bolt(cr, x + math.cos(a) * 10.5, -38.5 + math.sin(a) * 4.5,
             x + math.cos(a) * (10.5 + reach), -38.5 + math.sin(a) * (4.5 + reach * 0.8), seed * 31 + n, k.accent)


def xray(pt):
    """Cartoon electrocution: bones flashing through."""
    cr = pt.cr
    hx, hy = pt.head_cx, pt.head_cy
    for side in (-1, 1):
        ellipse(cr, hx + side * pt.eye_dx, hy + pt.eye_y, 5.2, 6.0)
        paint(cr, INK, None, alpha=0.9)
    cr.new_path()
    cr.move_to(hx - 1.6, hy + pt.eye_y + 8.0)
    cr.line_to(hx, hy + pt.eye_y + 5.4)
    cr.line_to(hx + 1.6, hy + pt.eye_y + 8.0)
    cr.close_path()
    paint(cr, INK, None, alpha=0.9)
    rounded_rect(cr, hx - 7, hy + pt.eye_y + 10.5, 14, 4.4, 1.4)
    stroke(cr, INK, 1.3, 0.9)
    for dx in (-3.5, 0.0, 3.5):
        cr.new_path()
        cr.move_to(hx + dx, hy + pt.eye_y + 10.5)
        cr.line_to(hx + dx, hy + pt.eye_y + 14.9)
        stroke(cr, INK, 1.0, 0.9)
    by = pt.body_cy
    cr.new_path()
    cr.move_to(0, by - 9)
    cr.line_to(0, by + 9)
    stroke(cr, INK, 1.8, 0.85)
    for i in range(3):
        cr.new_path()
        cr.move_to(-9.5, by - 5 + i * 5.0)
        cr.curve_to(-5, by - 8 + i * 5.0, 5, by - 8 + i * 5.0, 9.5, by - 5 + i * 5.0)
        stroke(cr, INK, 1.6, 0.85)
