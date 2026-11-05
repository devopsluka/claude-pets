"""Render contact sheets of the pets to PNG (for eyeballing the art)."""

import math
import sys
from dataclasses import replace

import cairo

from .color import rgb, src
from .creature import ACCESSORIES, COATS, LEGENDS, PATTERNS, SPECIES, SPECIES_ORDER, Design, Pose, default_design, draw_pet

CELL_W, CELL_H = 150, 170


def _label(cr, text, x, y, color=(1, 1, 1), size=11):
    cr.select_font_face("Adwaita Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(size)
    ext = cr.text_extents(text)
    cr.move_to(x - ext.width / 2, y)
    src(cr, color, 0.85)
    cr.show_text(text)
    cr.new_path()


def sheet(path, cells, cols=6, scale=1.25, bg=("#2B2633", "#EDE8F2")):
    """cells: list of (label, design, pose)."""
    rows = math.ceil(len(cells) / cols)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, cols * CELL_W, rows * CELL_H)
    cr = cairo.Context(surf)
    for i, (label, design, pose) in enumerate(cells):
        cx, cy = i % cols, i // cols
        dark = (cx + cy) % 2 == 0
        src(cr, rgb(bg[0] if dark else bg[1]))
        cr.rectangle(cx * CELL_W, cy * CELL_H, CELL_W, CELL_H)
        cr.fill()
        cr.save()
        cr.translate(cx * CELL_W + CELL_W / 2, cy * CELL_H + CELL_H - 34)
        cr.scale(scale, scale)
        draw_pet(cr, design, pose)
        cr.restore()
        _label(cr, label, cx * CELL_W + CELL_W / 2, cy * CELL_H + CELL_H - 10,
               (1, 1, 1) if dark else (0.15, 0.12, 0.18))
    surf.write_to_png(path)
    return path


def species_sheet(path):
    cells = []
    for name in SPECIES_ORDER:
        cells.append((SPECIES[name]["label"], default_design(name), Pose(t=0.4)))
    return sheet(path, cells, cols=6)


def legends_sheet(path):
    """The human characters: looks, faces and signature props."""
    cells = []
    for name in LEGENDS:
        cells.append((SPECIES[name]["label"], default_design(name), Pose(t=0.4)))
    cells.append(("turned", default_design("tyson"), Pose(t=0.4, facing=1.0, look=(1, 0))))
    for name in LEGENDS:
        cells.append((name + " happy", default_design(name), Pose(t=0.4, eye="happy", mouth="grin", arm_r=2.5)))
    cells.append(("alt coat", default_design("snoop", 1), Pose(t=0.4, eye="heart")))
    extras = [
        ("punch", "tyson", dict(hand_r=(42, -26), hand_l=(-12, -30), lean=0.14, facing=0.9, brow="angry", mouth="teeth")),
        ("toke", "snoop", dict(hand_r=(9, -34), item="joint", item_glow=1.0, mouth="o", eye="closed")),
        ("line", "pablo", dict(prop="mirror", prop_t=0.34, sit=0.6, head_dy=13, lean=0.0, look=(0, 1), eye="wide")),
        ("eureka", "einstein", dict(item="bulb", item_at="over", item_glow=1.0, hand_r=(14, -78), eye="sparkle", mouth="grin")),
        ("coil", "tesla", dict(prop="coil", prop_t=0.31, facing=0.7, hand_r=(30, -30), eye="sparkle", mouth="grin")),
        ("zap", "tesla", dict(shock=True, flash=0.9, eye="wide", mouth="teeth")),
        ("champ", "tyson", dict(prop="belt", hand_l=(-21, -86), hand_r=(21, -86), eye="happy", mouth="grin")),
        ("joint", "snoop", dict(item="joint", item_at="mouth", item_glow=0.3, sit=1.0, prop="laptop")),
        ("cash", "pablo", dict(item="bills", arm_r=1.2, eye="happy", mouth="grin")),
        ("board", "einstein", dict(prop="chalkboard", prop_t=1.0, prop_side=-1.0, facing=-0.7, hand_l=(-32, -46), tail_side=1.0)),
        ("pigeon", "tesla", dict(item="pigeon", item_at="over", look=(0, -1), eye="happy")),
        ("shock hair", "einstein", dict(shock=True, eye="wide", mouth="o")),
        ("asleep", "pablo", dict(lie=1.0, eye="closed", hat="nightcap")),
        ("sad", "tyson", dict(brow="sad", mouth="frown", marks=frozenset({"tear"}), ear=-1.0)),
        ("crown", "snoop", dict()),
        ("sign", "einstein", dict(prop="sign", prop_text="?", arm_r=2.25, mouth="o")),
        ("book", "tesla", dict(prop="book", sit=1.0, glasses=True, look=(0.4, 0.8))),
        ("party", "pablo", dict(hat="party", lift=14, arm_l=2.4, arm_r=2.4, eye="sparkle", mouth="grin")),
    ]
    for label, name, kw in extras:
        design = default_design(name)
        if label == "crown":
            design.accessory = "crown"
        cells.append((label, design, Pose(t=0.4, **kw)))
    return sheet(path, cells, cols=6)


def coats_sheet(path):
    cells = []
    for name in SPECIES_ORDER:
        for i in range(len(COATS[name])):
            cells.append(("%s %d" % (name, i), default_design(name, i, i), Pose(t=0.4)))
    return sheet(path, cells, cols=8, scale=1.0)


def faces_sheet(path, species="cat"):
    d = default_design(species)
    faces = [
        ("open", dict()), ("blink", dict(eye_open=0.1)), ("happy", dict(eye="happy", mouth="grin")),
        ("closed", dict(eye="closed")), ("wide", dict(eye="wide", mouth="o")),
        ("sparkle", dict(eye="sparkle", mouth="grin")), ("heart", dict(eye="heart", mouth="tongue", blush=1.0)),
        ("spiral", dict(eye="spiral", mouth="wavy", marks=frozenset({"dizzy"}))),
        ("x", dict(eye="x", mouth="frown")), ("squeeze", dict(eye="squeeze", mouth="teeth", marks=frozenset({"sweat"}))),
        ("sleepy", dict(eye="sleepy", mouth="flat")), ("angry", dict(brow="angry", mouth="teeth", marks=frozenset({"anger"}))),
        ("sad", dict(brow="sad", mouth="frown", marks=frozenset({"tear"}), ear=-1.0)),
        ("gloom", dict(brow="sad", mouth="wavy", marks=frozenset({"gloom", "cloud"}), ear=-1.0)),
        ("sick", dict(eye="sleepy", mouth="flat", marks=frozenset({"thermo", "bandage"}))),
        ("yawn", dict(eye="closed", mouth="yawn")), ("look-r", dict(facing=1.0, look=(1, 0))),
        ("look-l", dict(facing=-1.0, look=(-1, 0), tail_side=1.0)),
    ]
    cells = [(label, d, Pose(t=0.3, **kw)) for label, kw in faces]
    return sheet(path, cells, cols=6)


def poses_sheet(path, species="cat"):
    d = default_design(species)
    poses = [
        ("sit", dict(sit=1.0)), ("loaf", dict(lie=1.0, eye="closed", hat="nightcap")),
        ("wave", dict(arm_r=2.6, eye="happy", mouth="grin")), ("jump", dict(lift=16, squash=-0.4, arm_l=2.4, arm_r=2.4, eye="sparkle", mouth="grin", hat="party")),
        ("squash", dict(squash=0.9, eye="squeeze")), ("held", dict(held=True, dangle=0.35, eye="wide", mouth="o", arm_l=0.1, arm_r=0.1)),
        ("laptop", dict(sit=1.0, prop="laptop", prop_t=0.3, look=(0, 0.6))), ("book", dict(sit=1.0, prop="book", look=(0.4, 0.8))),
        ("magnifier", dict(prop="magnifier", arm_r=1.9, head_tilt=0.08)), ("clipboard", dict(prop="clipboard", prop_t=2.4, look=(0, 0.8))),
        ("mug", dict(prop="mug", prop_t=0.2, eye="sleepy", arm_r=0.9)), ("flag", dict(prop="flag", arm_r=1.0, eye="happy", mouth="grin")),
        ("sign", dict(prop="sign", prop_text="!", arm_r=2.2, eye="wide", mouth="o")), ("sign?", dict(prop="sign", prop_text="?", prop_side=-1.0, arm_l=2.2, head_tilt=-0.12)),
        ("terminal", dict(prop="terminal", prop_t=1.2, facing=0.8, look=(1, 0.5), arm_fwd_r=0.0, arm_r=1.0)),
        ("globe", dict(prop="globe", prop_t=1.0, facing=0.7, look=(1, -0.8))),
        ("gear", dict(prop="gear", prop_t=0.5, prop_side=-1.0, facing=-0.7, look=(-1, -0.8), tail_side=1.0)),
        ("stuffed", dict(belly=1.0, sit=1.0, eye="sleepy", mouth="wavy")),
    ]
    cells = [(label, d, Pose(t=0.3, **kw)) for label, kw in poses]
    return sheet(path, cells, cols=6)


def accessories_sheet(path):
    cells = []
    species = list(SPECIES_ORDER)
    for i, acc in enumerate(ACCESSORIES):
        name = species[i % len(species)]
        cells.append((acc, replace(default_design(name, 0, i), accessory=acc), Pose(t=0.3)))
    for i, pat in enumerate(PATTERNS):
        for name in ("cat", "dog", "bunny"):
            if pat in SPECIES[name]["patterns"]:
                cells.append(("%s %s" % (name, pat), replace(default_design(name, i % 3), pattern=pat), Pose(t=0.3)))
    return sheet(path, cells, cols=6)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    which = sys.argv[2:] or ["species", "legends", "coats", "faces", "poses", "accessories"]
    for name in which:
        fn = globals()[name.split(":")[0] + "_sheet"]
        args = name.split(":")[1:]
        print(fn("%s/%s.png" % (out, name.replace(":", "-")), *args))
