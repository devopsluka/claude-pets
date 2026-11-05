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

from .color import INK, WHITE, darken, lighten, luminance, mix, outline_of, rgb, src
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


def ribbon_path(cr, pts, w0, w1, steps=18):
    """Outline of a band along a cubic bezier, ``w0`` wide at the root tapering to ``w1``."""
    left, right = [], []
    tx = ty = 0.0
    for i in range(steps + 1):
        t = i / steps
        x, y = bezier(pts, t)
        ax, ay = bezier(pts, max(0.0, t - 0.02))
        bx, by = bezier(pts, min(1.0, t + 0.02))
        n = math.hypot(bx - ax, by - ay) or 1.0
        tx, ty = (bx - ax) / n, (by - ay) / n
        w = (w0 + (w1 - w0) * t) / 2.0
        left.append((x - ty * w, y + tx * w))
        right.append((x + ty * w, y - tx * w))
    cr.new_path()
    cr.move_to(*left[0])
    for q in left[1:]:
        cr.line_to(*q)
    reach = w1 * 0.9
    cr.curve_to(left[-1][0] + tx * reach, left[-1][1] + ty * reach,
                right[-1][0] + tx * reach, right[-1][1] + ty * reach, right[-1][0], right[-1][1])
    for q in reversed(right[:-1]):
        cr.line_to(*q)
    cr.close_path()


def mass(cr, shapes, fill, line, lw=LW):
    """Overlapping shapes that read as one piece: a shared outline and no inner seams."""
    for shape in shapes:
        shape()
        src(cr, line)
        cr.set_line_width(lw * 2)
        cr.stroke()
    for shape in shapes:
        shape()
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
    elif kind == "flattop":
        rounded_rect(cr, -rx + 5.0 + ox, -ry - 7.5, 2 * (rx - 5.0), 18.0, 3.0)
        paint(cr, k.hair, k.hair_line)
    elif kind == "combover":
        cr.save()
        cr.rectangle(-60, -70, 120, 64)
        cr.clip()
        blob(cr, ox, -2.0, rx + 3.0, ry + 3.0, pt.head_kt, pt.head_kb)
        paint(cr, k.hair, k.hair_line)
        cr.restore()
    elif kind == "long":
        sway = pose.tail * 1.2
        end = min(36.0, -4.0 - pt.head_cy)

        def curtain(side):
            return lambda: ribbon_path(cr, ((side * (rx - 3.0) + ox, -10.0), (side * (rx + 5.0) + ox, 4.0),
                                            (side * (rx + 4.5) + sway, 22.0), (side * (rx + 1.0) + sway * 1.4, end)),
                                       13.0, 9.0)

        mass(cr, [lambda: blob(cr, ox, -4.0, rx + 3.0, ry + 1.5, pt.head_kt, pt.head_kb), curtain(-1), curtain(1)],
             k.hair, k.hair_line)
    elif kind == "twintails":
        droop = max(0.0, -pose.ear)
        sway = pose.tail * 2.6
        out = 1.0 - 0.35 * droop
        end = min(44.0, -3.0 - pt.head_cy)
        for side in (-1, 1):
            pts = ((side * (rx - 2.0) + ox, -ry + 8.0), (side * (rx + 10.0 * out) + ox, -ry + 12.0),
                   (side * (rx + 9.5 * out) + sway, 16.0), (side * (rx + 4.0 * out) + sway * 1.5, end - droop * 2.0))
            ribbon_path(cr, pts, 13.0, 4.5)
            paint(cr, k.hair, k.hair_line)
            if not pt.flat:
                cr.new_path()
                cr.move_to(pts[0][0] + side * 2.0, pts[0][1] + 3.0)
                cr.curve_to(pts[1][0], pts[1][1] + 4.0, pts[2][0] - side * 1.0, pts[2][1],
                            pts[3][0] - side * 1.5, pts[3][1] - 8.0)
                stroke(cr, lighten(k.hair, 0.3), 1.3, 0.7)
        blob(cr, ox, -3.0, rx + 2.5, ry + 1.5, pt.head_kt, pt.head_kb)
        paint(cr, k.hair, k.hair_line)
    elif kind == "bouffant":
        puff = 1.12 if pose.shock else 1.0
        blobs = ((-15.0, -ry - 3.0, 13.0), (0.0, -ry - 8.5, 14.5), (15.0, -ry - 3.0, 13.0),
                 (-rx - 1.0, -ry + 7.0, 11.5), (rx + 1.0, -ry + 7.0, 11.5),
                 (-rx - 5.0, 2.0, 10.0), (rx + 5.0, 2.0, 10.0),
                 (-rx - 4.0, 14.0, 8.5), (rx + 4.0, 14.0, 8.5))
        cloud(cr, [(x + ox, y, r * puff) for x, y, r in blobs], k.hair, k.hair_line)
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
    if kind in ("buzz", "braids", "flattop"):
        buzz = kind != "braids"
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
        paint(cr, k.hair, None, alpha=0.72 if kind == "buzz" else 1.0)
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
    elif kind == "combover":
        cr.new_path()
        cr.move_to(-rx - 3, -2)
        cr.line_to(-rx - 3, top)
        cr.line_to(rx + 3, top)
        cr.line_to(rx + 3, -2)
        cr.curve_to(rx - 4, -ry + 12, 10 + ox, -ry + 10, ox, -ry + 10)
        cr.curve_to(-10 + ox, -ry + 10, -rx + 4, -ry + 12, -rx - 3, -2)
        cr.close_path()
        paint(cr, k.hair)
    elif kind == "long":
        part = ox + 3.0
        cr.new_path()
        cr.move_to(-rx - 3, 16)
        cr.line_to(-rx - 3, top)
        cr.line_to(rx + 3, top)
        cr.line_to(rx + 3, 16)
        cr.curve_to(rx - 2.5, 2, rx - 6, -ry + 8, part, -ry + 6.5)
        cr.curve_to(-rx + 6 + ox, -ry + 8, -rx + 2.5, 2, -rx - 3, 16)
        cr.close_path()
        paint(cr, k.hair)
        cr.new_path()
        cr.move_to(part, -ry + 6.5)
        cr.line_to(part * 0.7, top)
        stroke(cr, darken(k.hair, 0.25), 1.1)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(part + side * 4, -ry + 5)
            cr.curve_to(side * 12 + ox, -ry + 5, side * (rx - 4), -ry + 12, side * (rx - 1), 4)
            stroke(cr, light, 1.3, 0.55)
    elif kind == "twintails":
        b = -ry
        bangs = ((rx - 8.0, b + 10.0), (15.0, b + 17.0), (10.0, b + 10.5), (4.0, b + 17.5), (-2.0, b + 10.5),
                 (-8.0, b + 17.0), (-13.0, b + 10.0), (-17.5, b + 16.0))
        cr.new_path()
        cr.move_to(-rx - 3, 12)
        cr.line_to(-rx - 3, top)
        cr.line_to(rx + 3, top)
        cr.line_to(rx + 3, 12)
        cr.curve_to(rx - 1, 6, rx - 4, -2, rx - 5.5 + ox, b + 15)
        for x, y in bangs:
            cr.line_to(x + ox, y)
        cr.curve_to(-rx + 4, -2, -rx + 1, 6, -rx - 3, 12)
        cr.close_path()
        paint(cr, k.hair)
        cr.new_path()
        cr.move_to(-6 + ox, b + 4)
        cr.curve_to(-2 + ox, b + 2.5, 6 + ox, b + 2.5, 10 + ox, b + 4.5)
        stroke(cr, light, 1.6, 0.6)
    elif kind in ("curly", "wild", "bouffant"):
        y = -ry + {"curly": 12.5, "bouffant": 11.0}.get(kind, 9.0)
        dip = {"curly": 3.6, "bouffant": 3.0}.get(kind, 2.2)
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
    elif kind == "combover":
        o = -f * 1.5
        cr.new_path()
        cr.move_to(-rx + 0.5 + o, -ry + 13.0)
        cr.curve_to(-rx + 4.0 + o, -ry - 5.0, -4.0 + o, -ry - 9.5, rx + 3.5 + o, -ry + 2.0)
        cr.curve_to(rx + 1.5 + o, -ry + 8.0, rx - 6.0 + o, -ry + 9.0, 8.0 + o, -ry + 10.0)
        cr.curve_to(-2.0 + o, -ry + 11.0, -14.0 + o, -ry + 15.0, -rx + 0.5 + o, -ry + 13.0)
        cr.close_path()
        paint(cr, k.hair, k.hair_line, lw=1.8)
        if not pt.flat:
            for dy, color, alpha in ((-1.0, lighten(k.hair, 0.4), 0.9), (3.5, darken(k.hair, 0.18), 0.8)):
                cr.new_path()
                cr.move_to(-rx + 6.0 + o, -ry + 8.0 + dy)
                cr.curve_to(-6.0 + o, -ry - 3.0 + dy, 10.0 + o, -ry - 3.5 + dy, rx - 2.0 + o, -ry + 3.0 + dy * 0.6)
                stroke(cr, color, 1.2, alpha)
    elif kind == "twintails":
        for side in (-1, 1):
            x, y = side * (rx + 1.5) - f * 1.5, -ry + 9.5
            rounded_rect(cr, x - 3.2, y - 4.2, 6.4, 8.4, 2.0)
            paint(cr, rgb("#2A2630"), INK, lw=1.3)
            if not pt.flat:
                cr.new_path()
                cr.move_to(x - 3.0, y)
                cr.line_to(x + 3.0, y)
                stroke(cr, rgb("#FF6FAE"), 1.5)
    elif kind == "bouffant" and not pt.flat:
        for x, y in ((-14, -ry - 6), (2, -ry - 12), (15, -ry - 5), (-rx - 5, 1), (rx + 5, 1), (-rx - 4, 13), (rx + 4, 13)):
            cr.new_path()
            cr.arc(x - f * 1.5, y, 4.0, math.pi * 1.1, math.pi * 1.75)
            stroke(cr, k.hair_line, 1.1, 0.55)


def eye_details(pt, f):
    """Lashes and lids (and an anime glint in the iris) on top of the shared eyes."""
    cr, k, pose = pt.cr, pt.k, pt.p
    scale, ey = pt.eye_scale, pt.eye_y
    lashes = pt.spec.get("lashes")
    for side in (-1, 1):
        kind = pose.eye
        if kind == "wink":
            kind = "happy" if side == 1 else "open"
        narrow = 1 - 0.2 * max(0.0, side * f)
        cx = side * pt.eye_dx + f * 5.5
        rx, ry = 4.4 * scale * narrow, 5.9 * scale
        ex, eyy, rr = cx, ey, ry
        openness = 1.0
        if kind in ("open", "sleepy", "angry", "sad"):
            openness = max(0.0, min(1.0, pose.eye_open))
            if kind == "sleepy":
                openness = min(openness, 0.55)
            if openness < 0.2:
                kind = "closed"
            else:
                ex = cx + pose.look[0] * 1.5
                eyy = ey + pose.look[1] * 1.3 + (1 - openness) * ry * 0.45
                rr = ry * openness
        elif kind == "wide":
            rx, rr = ry * 1.02 * narrow, ry * 1.02
        elif kind == "sparkle":
            rx, rr = rx * 1.18, ry * 1.1
        if kind in ("open", "sleepy", "angry", "sad", "wide", "sparkle"):
            if lashes:
                cr.save()
                cr.translate(ex, eyy)
                cr.scale(rx, rr)
                cr.new_path()
                cr.arc(0, 0, 1.0, math.pi * 1.12, math.pi * 1.88)
                cr.restore()
                stroke(cr, INK, 1.7)
                for th in (1.0, 1.32):
                    px, py = ex + side * rx * math.sin(th), eyy - rr * math.cos(th)
                    cr.new_path()
                    cr.move_to(px, py)
                    cr.line_to(px + side * 2.7 * math.sin(th + 0.3), py - 2.7 * math.cos(th + 0.3))
                    stroke(cr, INK, 1.3)
            if pt.spec.get("anime") and kind == "open" and openness > 0.6:
                ellipse(cr, ex, eyy + rr * 0.45, rx * 0.62, rr * 0.3)
                paint(cr, lighten(k.eye, 0.5), None, alpha=0.8)
        elif kind in ("happy", "closed") and lashes:
            x, y = cx + side * rx * 1.05, ey + (2.2 if kind == "happy" else 0.2)
            cr.new_path()
            cr.move_to(x, y)
            cr.line_to(x + side * 2.4, y - 2.0)
            stroke(cr, INK, 1.3)


def lips(pt, nx, my):
    """Lipstick over a closed mouth; open mouths keep the shared drawing."""
    cr, kind = pt.cr, pt.p.mouth
    if kind not in ("smile", "flat", "cat"):
        return
    col = rgb(pt.spec["lips"])
    curve = 1.2 if kind != "flat" else 0.4
    cr.new_path()
    cr.move_to(nx - 4.0, my + 0.2)
    cr.curve_to(nx - 2.0, my - 1.9, nx + 2.0, my - 1.9, nx + 4.0, my + 0.2)
    cr.curve_to(nx + 2.2, my + 3.0 + curve * 0.4, nx - 2.2, my + 3.0 + curve * 0.4, nx - 4.0, my + 0.2)
    cr.close_path()
    paint(cr, col, darken(col, 0.3), lw=0.9)
    cr.new_path()
    cr.move_to(nx - 3.6, my + 0.4)
    cr.curve_to(nx - 1.2, my + 0.4 + curve, nx + 1.2, my + 0.4 + curve, nx + 3.6, my + 0.4)
    stroke(cr, darken(col, 0.45), 1.0)
    ellipse(cr, nx - 1.4, my + 1.9, 1.1, 0.5)
    paint(cr, WHITE, None, alpha=0.45)


def headwear(pt, f):
    """A legend's own headwear (a contextual hat — party, hardhat, nightcap — replaces the hat)."""
    if pt.spec.get("headset"):
        _headset(pt, f)
    if pt.spec.get("hat") == "brim" and not pt.p.hat:
        _brim_hat(pt, f)


def _headset(pt, f):
    cr, k = pt.cr, pt.k
    dark = rgb("#3A3842")
    for side in (-1, 1):
        x = side * (pt.head_rx - 0.5) - f * 1.5
        rounded_rect(cr, x - 3.4, -3.0, 6.8, 12.0, 2.6)
        paint(cr, dark, INK, lw=1.4)
        if not pt.flat:
            ellipse(cr, x, 3.0, 1.8, 3.6)
            stroke(cr, k.accent, 1.2)
    if pt.flat:
        return
    side = 1.0 if f >= 0 else -1.0
    x0 = side * (pt.head_rx - 0.5) - f * 1.5
    mx, my = f * 8.0 + side * 8.0, pt.eye_y + 10.5
    cr.new_path()
    cr.move_to(x0, 7.0)
    cr.curve_to(x0, 12.0, mx + side * 6.0, my + 2.0, mx, my)
    stroke(cr, dark, 1.5)
    ellipse(cr, mx, my, 1.9, 1.9)
    paint(cr, k.accent, INK, lw=0.9)


def _brim_hat(pt, f):
    """The big wide-brimmed hat, worn low and at an angle."""
    cr, k = pt.cr, pt.k
    hat, line = k.fur, k.line
    y0 = pt.eye_y - 9.0
    top = -pt.head_ry - 5.0
    if not pt.flat:
        cr.save()                               # the brim's shadow over the brow
        pt.head_path()
        cr.clip()
        ellipse(cr, f * 2.0, y0 + 5.0, pt.head_rx + 2.0, 6.5, -0.10)
        src(cr, INK, 0.16)
        cr.fill()
        cr.restore()
    cr.save()
    cr.translate(f * 2.0, 0)
    cr.rotate(-0.10)
    ellipse(cr, 0, y0, 42.0, 6.5)
    paint(cr, hat, line)

    def crown():
        cr.new_path()
        cr.move_to(-23.5, y0)
        cr.curve_to(-25.0, y0 - 16.0, -17.0, top, 0.0, top)
        cr.curve_to(17.0, top, 25.0, y0 - 16.0, 23.5, y0)
        cr.close_path()

    crown()
    paint(cr, hat, line)
    if not pt.flat:
        cr.save()
        crown()
        cr.clip()
        cr.rectangle(-30, y0 - 6.0, 60, 4.5)
        src(cr, k.accent)
        cr.fill()
        cr.restore()
        cr.new_path()
        cr.arc(-6.0, y0 - 9.0, 12.0, math.pi * 1.15, math.pi * 1.45)
        stroke(cr, WHITE, 1.4, 0.4)
    cr.restore()


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
    if kind == "cleft":
        cr.new_path()
        cr.move_to(nx - 0.6, my + 8.6)
        cr.curve_to(nx - 0.2, my + 10.0, nx + 0.2, my + 10.0, nx + 0.6, my + 8.6)
        stroke(cr, k.skin_line, 1.3, 0.75)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(nx + side * 9.0, my + 5.5)
            cr.curve_to(nx + side * 7.5, my + 8.5, nx + side * 5.0, my + 10.0, nx + side * 3.0, my + 10.5)
            stroke(cr, k.skin_line, 1.1, 0.35)
    elif kind == "mustache":
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
    elif outfit == "tie":
        cr.new_path()
        cr.move_to(-7.0, neck - 2)
        cr.line_to(7.0, neck - 2)
        cr.line_to(0, neck + 13.5)
        cr.close_path()
        paint(cr, WHITE)
        tie = k.accent
        cr.new_path()
        cr.move_to(-2.0, neck + 1.5)
        cr.line_to(2.0, neck + 1.5)
        cr.line_to(3.4, by + bry - 3.5)
        cr.line_to(0, by + bry - 0.5)
        cr.line_to(-3.4, by + bry - 3.5)
        cr.close_path()
        paint(cr, tie, outline_of(tie), lw=1.0)
        rounded_rect(cr, -2.7, neck - 1.6, 5.4, 3.8, 1.3)
        paint(cr, tie, outline_of(tie), lw=1.0)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 7.2, neck - 2)
            cr.line_to(side * 4.2, neck + 14.5)
            stroke(cr, lighten(k.fur, 0.3), 1.7)
        ellipse(cr, -11.0, neck + 6.0, 1.3, 1.0)
        paint(cr, rgb("#E5E7EB"))
    elif outfit == "jacket":
        tee = darken(k.fur, 0.35) if luminance(k.fur) > 0.25 else lighten(k.fur, 0.18)
        cr.new_path()
        cr.move_to(-8.0, neck - 2)
        cr.line_to(8.0, neck - 2)
        cr.line_to(6.0, by + bry)
        cr.line_to(-6.0, by + bry)
        cr.close_path()
        paint(cr, tee)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 1.2, by - 6.0)
            cr.curve_to(side * 3.0, by - 3.5, side * 5.5, by - 3.5, side * 6.5, by - 6.0)
            stroke(cr, mix(tee, INK, 0.5), 1.2, 0.7)
            cr.new_path()
            cr.move_to(side * 8.0, neck - 2.5)
            cr.line_to(side * 14.0, neck + 5.0)
            cr.line_to(side * 6.6, neck + 6.5)
            cr.close_path()
            paint(cr, lighten(k.fur, 0.12), k.line, lw=1.3)
            cr.new_path()
            cr.move_to(side * 6.6, neck + 6.5)
            cr.line_to(side * 6.0, by + bry)
            stroke(cr, lighten(k.fur, 0.35), 1.0, 0.8)
    elif outfit == "skirtsuit":
        cr.new_path()
        cr.move_to(-5.5, neck - 2)
        cr.line_to(5.5, neck - 2)
        cr.line_to(0, neck + 8.0)
        cr.close_path()
        paint(cr, k.skin)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * 5.5, neck - 2)
            cr.line_to(side * 10.5, neck + 3.0)
            cr.line_to(side * 2.0, neck + 7.0)
            cr.close_path()
            paint(cr, lighten(k.fur, 0.08), k.line, lw=1.3)
            for y in (neck + 11.0, neck + 15.5):
                ellipse(cr, side * 3.8, y, 1.0, 1.0)
                paint(cr, darken(k.fur, 0.35))
        cr.new_path()
        cr.rectangle(-40, by + 3.0, 80, 2.6)
        paint(cr, k.accent)
        cr.new_path()
        cr.move_to(0, by + 5.6)
        cr.line_to(0, by + bry)
        stroke(cr, darken(k.fur, 0.18), 1.1)
    elif outfit == "miku":
        skirt = rgb("#2A2630")
        cr.new_path()
        cr.rectangle(-40, by + 4.5, 80, 30)
        paint(cr, skirt)
        cr.new_path()
        cr.move_to(-40, by + 5.6)
        cr.line_to(40, by + 5.6)
        stroke(cr, k.accent, 1.4)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(0, neck + 4.0)
            cr.line_to(side * 8.0, neck - 2.0)
            cr.line_to(side * 10.0, neck + 3.5)
            cr.close_path()
            paint(cr, lighten(k.fur, 0.2), k.line, lw=1.2)
        cr.new_path()
        cr.move_to(-1.8, neck + 2.0)
        cr.line_to(1.8, neck + 2.0)
        cr.line_to(2.8, by - 0.5)
        cr.line_to(0, by + 2.5)
        cr.line_to(-2.8, by - 0.5)
        cr.close_path()
        paint(cr, k.accent, outline_of(k.accent), lw=1.0)
        ellipse(cr, 0, neck + 2.6, 2.4, 1.8)
        paint(cr, k.accent, outline_of(k.accent), lw=1.0)
    elif outfit == "military":
        cream = rgb("#F4F4F6")
        cr.new_path()
        cr.move_to(-6.5, neck - 2)
        cr.line_to(6.5, neck - 2)
        cr.line_to(5.0, by + 3.0)
        cr.line_to(-5.0, by + 3.0)
        cr.close_path()
        paint(cr, cream)
        cr.new_path()
        cr.rectangle(-40, by + 3.0, 80, 40)
        paint(cr, cream)
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(side * (brx - 4.0), by + 3.0)
            cr.line_to(side * (brx - 4.5), by + bry + 2)
            stroke(cr, rgb("#E11D48"), 1.4)
            cr.new_path()
            cr.move_to(side * 6.5, neck - 2)
            cr.line_to(side * 5.0, by + 3.0)
            stroke(cr, darken(k.fur, 0.25), 1.3)
            for i in range(3):
                rounded_rect(cr, side * 9.8 - 2.4, neck + 3.0 + i * 4.6, 4.8, 2.2, 0.8)
                paint(cr, SILVER, SILVER_D, lw=0.7)
        cr.new_path()
        cr.move_to(-40, by + 3.0)
        cr.line_to(40, by + 3.0)
        stroke(cr, darken(k.fur, 0.3), 1.3)
    elif outfit == "sequins":
        cr.new_path()
        cr.move_to(-9.0, neck - 2)
        cr.curve_to(-8.0, neck + 5.0, -3.0, neck + 6.5, 0, neck + 4.0)
        cr.curve_to(3.0, neck + 6.5, 8.0, neck + 5.0, 9.0, neck - 2)
        cr.close_path()
        paint(cr, k.skin)
        cr.new_path()
        cr.rectangle(-40, by + 2.0, 80, 2.8)
        paint(cr, k.accent)
        glint = lighten(k.fur, 0.55)
        for i, (x, y) in enumerate(((-12, -3), (-6, 5), (-13, 10), (1, 10), (8, 3), (13, -3), (12, 9), (5, 13),
                                    (-4, -1), (-8, 14), (2, -5))):
            ellipse(cr, x, by + y, 0.9, 0.9)
            paint(cr, glint)
        for i, (x, y) in enumerate(((-9, 0), (10, 7), (-2, 12))):
            size = 2.4 * (0.55 + 0.45 * math.sin(pt.p.t * 4.0 + i * 2.1))
            star_path(cr, x, by + y, size, size * 0.35, 4)
            paint(cr, WHITE, None, alpha=0.9)
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
        return
    gesture = pt.p.hand_pose
    if gesture == "flex":
        dx, dy = ex - sx, ey - sy
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        if ny > 0:
            nx, ny = -nx, -ny
        ellipse(cr, sx + dx * 0.45 + nx * 3.0, sy + dy * 0.45 + ny * 3.0, 6.4, 4.8, math.atan2(dy, dx))
        paint(cr, k.limb, k.limb_line, lw=1.8)
    elif gesture == "thumbs":
        rounded_rect(cr, ex - 1.8, ey - 9.0, 3.6, 7.0, 1.8)
        paint(cr, k.skin, k.skin_line, lw=1.4)
    elif gesture == ("point_r" if side > 0 else "point_l"):
        tube(cr, ((ex, ey), (ex + side * 7.5, ey - 1.0)), 2.6, k.skin, k.skin_line, lw=1.3)
    r = 3.9 * max(1.0, pt.spec.get("arm_w", 7.0) / 7.0)
    ellipse(cr, ex, ey, r, r)
    paint(cr, k.skin, k.skin_line, lw=1.7)
    if pt.spec.get("nails") and not pt.flat:
        for i in (-1, 0, 1):
            ellipse(cr, ex + i * 1.9, ey - 2.7 + abs(i) * 0.6, 0.85, 1.05)
            paint(cr, k.accent)


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


def _dumbbell(cr, x, y, k):
    tube(cr, ((x - 9.0, y), (x + 9.0, y)), 2.2, SILVER, SILVER_D, lw=1.0)
    plate = rgb("#3A3842")
    for side in (-1, 1):
        rounded_rect(cr, x + side * 9.0 - 2.2, y - 5.5, 4.4, 11.0, 1.4)
        paint(cr, plate, INK, lw=1.3)
        rounded_rect(cr, x + side * 6.0 - 1.4, y - 3.8, 2.8, 7.6, 1.0)
        paint(cr, k.accent, k.accent_line, lw=1.0)


def _pen(cr, x, y, direction):
    cr.save()
    cr.translate(x, y)
    cr.rotate(-0.5 * direction)
    tube(cr, ((0, 4.0), (0, -12.0)), 3.6, rgb("#1E1E24"), INK, lw=1.0)
    tube(cr, ((0, -12.0), (0, -15.0)), 2.2, GOLD, outline_of(GOLD), lw=0.8)
    cr.restore()


def _leek(cr, x, y, angle):
    green, dark = rgb("#5DBB63"), rgb("#3E9B4A")
    cr.save()
    cr.translate(x, y)
    cr.rotate(angle)
    for tx, ty in ((-3.5, -25.0), (3.2, -23.0)):
        tube(cr, ((0, -13.0), (tx, ty)), 3.4, dark, outline_of(dark), lw=1.1)
    tube(cr, ((0, -1.0), (0, -15.0)), 4.4, green, outline_of(green), lw=1.1)
    tube(cr, ((0, 7.0), (0, -1.5)), 4.8, rgb("#F7F7EE"), rgb("#A8AE96"), lw=1.1)
    for dx in (-1.2, 0.0, 1.2):
        cr.new_path()
        cr.move_to(dx, 9.5)
        cr.line_to(dx * 1.8, 12.0)
        stroke(cr, rgb("#C9B98A"), 0.9)
    cr.restore()


def _mic_stand(cr, x, y, angle):
    """Freddie's half mic stand: a chrome bar with the mic on top."""
    cr.save()
    cr.translate(x, y)
    cr.rotate(angle)
    tube(cr, ((0, 9.0), (0, -21.0)), 2.6, SILVER, rgb("#6E7686"), lw=1.0)
    ellipse(cr, 0, -24.0, 3.6, 4.2)
    paint(cr, rgb("#4B4856"), INK, lw=1.2)
    for dy in (-25.5, -23.5):
        cr.new_path()
        cr.move_to(-2.6, dy)
        cr.line_to(2.6, dy)
        stroke(cr, rgb("#8D8A9C"), 0.7)
    cr.restore()


def _guitar(pt, x, y, direction):
    cr = pt.cr
    wood, neck = rgb("#D9A066"), rgb("#6B4A2F")
    cr.save()
    cr.translate(x, y)
    cr.rotate(-0.9 * direction)
    rounded_rect(cr, -1.7, -31.0, 3.4, 22.0, 1.0)
    paint(cr, neck, outline_of(neck), lw=1.1)
    rounded_rect(cr, -2.6, -36.0, 5.2, 6.5, 1.4)
    paint(cr, neck, outline_of(neck), lw=1.1)
    mass(cr, [lambda: ellipse(cr, 0, 2.0, 9.0, 8.0), lambda: ellipse(cr, 0, -8.0, 6.8, 5.8)], wood, outline_of(wood),
         lw=1.0)
    ellipse(cr, 0, -3.5, 2.3, 2.3)
    paint(cr, INK)
    rounded_rect(cr, -3.0, 3.0, 6.0, 1.6, 0.6)
    paint(cr, neck)
    for dx in (-0.8, 0.0, 0.8):
        cr.new_path()
        cr.move_to(dx, 3.5)
        cr.line_to(dx, -33.0)
        stroke(cr, SILVER, 0.35)
    cr.restore()


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
        y = pt.head_cy - pt.head_ry - {"wild": 24.0, "curly": 24.0, "bouffant": 32.0}.get(pt.spec.get("hair"), 19.0)
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
    elif name == "dumbbell":
        _dumbbell(cr, x, y, pt.k)
    elif name == "pen":
        _pen(cr, x, y, direction)
    elif name == "leek":
        _leek(cr, x, y, pose.item_glow)
    elif name == "mic":
        _mic_stand(cr, x, y, pose.item_glow)
    elif name == "guitar":
        _guitar(pt, x, y, direction)
        if at != "over":                         # the strumming hand stays in front of the strings
            side = -1 if at == "hand_l" else 1
            hand(pt, side, x, y, x, y)


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
