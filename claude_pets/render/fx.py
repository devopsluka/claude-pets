"""Little particles that make feelings visible: hearts, sparkles, Zzz, confetti…

Positions are in pet units relative to the pet's ground point (same frame the
pet itself is drawn in), so they scale and move with it.
"""

import math
import random

import cairo

from .color import INK, WHITE, outline_of, rgb, src
from .creature import TAU, drop_path, ellipse, heart_path, paint, rounded_rect, star_path, stroke
from .human import bolt

ROSE = rgb("#FF5C8A")
GOLD = rgb("#FCD34D")
VIOLET = rgb("#A78BFA")
SKY = rgb("#8FD3FF")
GREEN = rgb("#4ADE80")
RED = rgb("#F43F5E")
CONFETTI = tuple(rgb(c) for c in ("#F97316", "#4ADE80", "#8B5CF6", "#38BDF8", "#FB7185", "#FCD34D"))


class Particle:
    __slots__ = ("kind", "x", "y", "vx", "vy", "ay", "age", "life", "size", "rot", "vrot",
                 "color", "text", "sway", "delay")

    def __init__(self, kind, x, y, vx=0.0, vy=0.0, ay=0.0, life=1.0, size=1.0, rot=0.0, vrot=0.0,
                 color=None, text="", sway=0.0, delay=0.0):
        self.kind = kind
        self.x, self.y = x, y
        self.vx, self.vy, self.ay = vx, vy, ay
        self.age, self.life = 0.0, life
        self.size, self.rot, self.vrot = size, rot, vrot
        self.color = color
        self.text = text
        self.sway = sway
        self.delay = delay


class Particles:
    def __init__(self, rng=None):
        self.items = []
        self.rng = rng or random.Random()

    def __bool__(self):
        return bool(self.items)

    def clear(self):
        self.items = []

    def fps(self):
        """Repaint rate the live particles need (0 when there are none)."""
        need = 0
        for p in self.items:
            if p.kind == "text" and p.text == "z":
                rate = 4
            elif p.kind in ("note", "text", "heart", "check", "cross"):
                rate = 15
            elif p.kind == "sparkle":
                rate = 20
            elif p.kind == "smoke":
                rate = 12
            else:
                return 30
            if rate > need:
                need = rate
        return need

    def add(self, kind, x, y, **kw):
        if len(self.items) < 90:
            self.items.append(Particle(kind, x, y, **kw))

    # -- ready-made effects --------------------------------------------

    def hearts(self, n=3, x=0.0, y=-70.0):
        r = self.rng
        for i in range(n):
            self.add("heart", x + r.uniform(-16, 16), y + r.uniform(-4, 8), vy=-r.uniform(16, 26),
                     life=r.uniform(1.1, 1.6), size=r.uniform(3.2, 4.8), sway=r.uniform(3, 7),
                     delay=i * 0.14)

    def sparkles(self, n=5, x=0.0, y=-50.0, spread=34.0):
        r = self.rng
        for i in range(n):
            self.add("sparkle", x + r.uniform(-spread, spread), y + r.uniform(-spread * 0.8, spread * 0.5),
                     vy=-r.uniform(2, 8), life=r.uniform(0.6, 1.1), size=r.uniform(3.0, 5.5),
                     vrot=r.uniform(-2, 2), delay=i * 0.07, color=GOLD if i % 2 else WHITE)

    def confetti(self, n=26, x=0.0, y=-60.0):
        r = self.rng
        for _ in range(n):
            a = r.uniform(-TAU * 0.42, -TAU * 0.08)
            sp = r.uniform(70, 150)
            self.add("confetti", x, y, vx=math.cos(a) * sp, vy=math.sin(a) * sp, ay=210.0,
                     life=r.uniform(1.3, 2.1), size=r.uniform(2.2, 3.8), rot=r.uniform(0, TAU),
                     vrot=r.uniform(-9, 9), color=r.choice(CONFETTI))

    def zzz(self, x=14.0, y=-66.0):
        self.add("text", x, y, vx=7.0, vy=-11.0, life=2.4, size=9.0, text="z", color=VIOLET, sway=2.5)

    def note(self, x=0.0, y=-78.0):
        r = self.rng
        self.add("note", x + r.uniform(-14, 14), y, vy=-14.0, life=1.6, size=5.0, sway=5.0,
                 color=r.choice(CONFETTI))

    def sweat(self, side=1.0, x=0.0, y=-66.0):
        r = self.rng
        for i in range(2):
            self.add("drop", x + side * 26, y + i * 5, vx=side * r.uniform(22, 40), vy=-r.uniform(20, 40),
                     ay=160.0, life=0.7, size=2.4, color=SKY)

    def dust(self, x=0.0, n=4):
        r = self.rng
        for i in range(n):
            side = -1 if i % 2 else 1
            self.add("puff", x + side * r.uniform(6, 14), -2.0, vx=side * r.uniform(14, 34), vy=-r.uniform(4, 14),
                     life=r.uniform(0.4, 0.7), size=r.uniform(3, 5))

    def steam(self, y=-72.0):
        for side in (-1, 1):
            self.add("puff", side * 26, y, vx=side * 14.0, vy=-16.0, life=0.8, size=4.0, color=WHITE)

    def stars(self, n=4, x=0.0, y=-10.0):
        r = self.rng
        for _ in range(n):
            a = r.uniform(-TAU * 0.45, -TAU * 0.05)
            sp = r.uniform(50, 100)
            self.add("star", x, y, vx=math.cos(a) * sp, vy=math.sin(a) * sp, ay=160.0, life=0.8,
                     size=r.uniform(3, 4.5), vrot=r.uniform(-6, 6), color=GOLD)

    def papers(self, n=5, y=-40.0):
        r = self.rng
        for _ in range(n):
            side = r.choice((-1, 1))
            self.add("paper", side * 10, y, vx=side * r.uniform(30, 70), vy=-r.uniform(40, 90), ay=190.0,
                     life=1.1, size=r.uniform(3.5, 5), rot=r.uniform(0, TAU), vrot=r.uniform(-6, 6))

    def smoke(self, x=0.0, y=-44.0, direction=1.0, n=1, big=False):
        r = self.rng
        for i in range(n):
            self.add("smoke", x + r.uniform(-2, 2), y + r.uniform(-2, 2), vx=direction * r.uniform(6, 16),
                     vy=-r.uniform(9, 17), life=r.uniform(1.6, 2.6), size=r.uniform(4.5, 6.5) * (1.5 if big else 1.0),
                     sway=r.uniform(1.5, 4.0), delay=i * 0.06)

    def pow(self, x=30.0, y=-34.0, text="POW!"):
        self.add("pow", x, y, life=0.65, size=13.0, text=text, rot=self.rng.uniform(-0.25, 0.25))
        self.stars(3, x, y)

    def bolts(self, n=3, x=0.0, y=-40.0, reach=34.0, color=None):
        r = self.rng
        for i in range(n):
            a = r.uniform(0, TAU)
            d = r.uniform(reach * 0.5, reach)
            self.add("bolt", x + math.cos(a) * 6, y + math.sin(a) * 6, vx=math.cos(a) * d, vy=math.sin(a) * d * 0.8,
                     life=r.uniform(0.10, 0.2), color=color or SKY, delay=i * 0.05, rot=r.uniform(0, 1000))

    def arc(self, x0, y0, x1, y1, color=None):
        """One lightning arc between two points."""
        self.add("bolt", x0, y0, vx=x1 - x0, vy=y1 - y0, life=self.rng.uniform(0.09, 0.16), color=color or SKY,
                 rot=self.rng.uniform(0, 1000))

    def bills(self, n=16, x=0.0, y=-70.0):
        r = self.rng
        for _ in range(n):
            a = r.uniform(-TAU * 0.42, -TAU * 0.08)
            sp = r.uniform(60, 130)
            self.add("bill", x, y, vx=math.cos(a) * sp, vy=math.sin(a) * sp, ay=170.0, life=r.uniform(1.6, 2.4),
                     size=r.uniform(3.4, 4.6), rot=r.uniform(0, TAU), vrot=r.uniform(-6, 6))

    def pop_text(self, text, color=None, x=0.0, y=-92.0, size=11.0, life=1.5):
        self.add("text", x, y, vy=-13.0, life=life, size=size, text=text, color=color or WHITE)

    def check(self, x=22.0, y=-74.0):
        self.add("check", x, y, vy=-9.0, life=1.0, size=5.0, color=GREEN)

    def cross(self, x=22.0, y=-74.0):
        self.add("cross", x, y, vy=-9.0, life=1.0, size=4.5, color=RED)

    # -- simulation -----------------------------------------------------

    def update(self, dt):
        if not self.items:
            return
        alive = []
        for p in self.items:
            if p.delay > 0:
                p.delay -= dt
                alive.append(p)
                continue
            p.age += dt
            if p.age >= p.life:
                continue
            p.vy += p.ay * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.rot += p.vrot * dt
            alive.append(p)
        self.items = alive

    def draw(self, cr):
        for p in self.items:
            if p.delay > 0:
                continue
            k = p.age / p.life
            fade = 1.0 if k < 0.6 else max(0.0, (1 - k) / 0.4)
            grow = min(1.0, p.age / 0.15)
            x = p.x + (math.sin(p.age * 4.0 + p.y) * p.sway if p.sway else 0.0)
            y = p.y
            kind = p.kind
            if kind == "heart":
                heart_path(cr, x, y, p.size * grow)
                paint(cr, ROSE, outline_of(ROSE), lw=1.2, alpha=fade)
            elif kind == "sparkle":
                tw = 0.6 + 0.4 * math.sin(p.age * 14.0)
                star_path(cr, x, y, p.size * grow * tw, p.size * 0.32 * grow * tw, 4, p.rot)
                paint(cr, p.color or GOLD, outline_of(GOLD), lw=0.9, alpha=fade)
            elif kind == "star":
                star_path(cr, x, y, p.size, p.size * 0.45, 5, p.rot)
                paint(cr, p.color or GOLD, outline_of(GOLD), lw=1.0, alpha=fade)
            elif kind == "confetti":
                cr.save()
                cr.translate(x, y)
                cr.rotate(p.rot)
                cr.scale(1.0, 0.35 + 0.65 * abs(math.cos(p.rot * 1.7)))
                rounded_rect(cr, -p.size, -p.size * 0.6, p.size * 2, p.size * 1.2, 0.6)
                cr.restore()
                paint(cr, p.color, None, alpha=fade)
            elif kind == "drop":
                drop_path(cr, x, y, p.size)
                paint(cr, p.color or SKY, rgb("#4A90C2"), lw=1.0, alpha=fade)
            elif kind == "puff":
                r = p.size * (0.6 + k * 0.9)
                ellipse(cr, x, y, r, r)
                paint(cr, p.color or rgb("#D8D2E0"), None, alpha=0.75 * (1 - k))
            elif kind == "paper":
                cr.save()
                cr.translate(x, y)
                cr.rotate(p.rot)
                rounded_rect(cr, -p.size * 0.7, -p.size, p.size * 1.4, p.size * 2, 0.8)
                cr.restore()
                paint(cr, WHITE, rgb("#8F879B"), lw=0.9, alpha=fade)
            elif kind == "note":
                col = p.color or VIOLET
                ellipse(cr, x, y, p.size * 0.52, p.size * 0.4, -0.4)
                paint(cr, col, None, alpha=fade)
                cr.new_path()
                cr.move_to(x + p.size * 0.42, y - 0.5)
                cr.line_to(x + p.size * 0.42, y - p.size * 1.5)
                cr.curve_to(x + p.size * 0.9, y - p.size * 1.4, x + p.size * 1.2, y - p.size * 1.0,
                            x + p.size * 1.1, y - p.size * 0.6)
                stroke(cr, col, 1.5, fade)
            elif kind == "check":
                s = p.size * grow
                ellipse(cr, x, y, s * 1.5, s * 1.5)
                paint(cr, p.color or GREEN, outline_of(GREEN), lw=1.1, alpha=fade)
                cr.new_path()
                cr.move_to(x - s * 0.7, y)
                cr.line_to(x - s * 0.15, y + s * 0.55)
                cr.line_to(x + s * 0.75, y - s * 0.55)
                stroke(cr, WHITE, 1.7, fade)
            elif kind == "cross":
                s = p.size * grow
                ellipse(cr, x, y, s * 1.5, s * 1.5)
                paint(cr, p.color or RED, outline_of(RED), lw=1.1, alpha=fade)
                for d in (-1, 1):
                    cr.new_path()
                    cr.move_to(x - s * 0.6, y - s * 0.6 * d)
                    cr.line_to(x + s * 0.6, y + s * 0.6 * d)
                    stroke(cr, WHITE, 1.7, fade)
            elif kind == "smoke":
                r = p.size * (0.7 + 1.7 * k)
                ellipse(cr, x, y, r, r * 0.9)
                paint(cr, rgb("#E9E6EE"), None, alpha=0.42 * (1 - k) * min(1.0, p.age / 0.12))
            elif kind == "bolt":
                bolt(cr, x - p.vx * p.age, y - p.vy * p.age, x - p.vx * p.age + p.vx, y - p.vy * p.age + p.vy,
                     int(p.rot) + int(p.age * 40), p.color or SKY, alpha=1 - k * 0.6)
            elif kind == "bill":
                green = rgb("#5BBF7A")
                cr.save()
                cr.translate(x, y)
                cr.rotate(p.rot)
                cr.scale(1.0, 0.4 + 0.6 * abs(math.cos(p.rot * 1.3)))
                rounded_rect(cr, -p.size * 1.6, -p.size * 0.8, p.size * 3.2, p.size * 1.6, 0.8)
                cr.restore()
                paint(cr, green, outline_of(green), lw=0.9, alpha=fade)
            elif kind == "pow":
                s = p.size * (0.5 + 0.5 * min(1.0, p.age / 0.09))
                star_path(cr, x, y, s * 1.25, s * 0.78, 9, p.rot)
                paint(cr, GOLD, rgb("#B45309"), lw=1.4, alpha=fade)
                cr.select_font_face("Adwaita Sans", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(s * 0.62)
                ext = cr.text_extents(p.text)
                cr.move_to(x - ext.width / 2 - ext.x_bearing, y - ext.height / 2 - ext.y_bearing)
                src(cr, RED, fade)
                cr.show_text(p.text)
                cr.new_path()
            elif kind == "text":
                size = p.size * (0.7 + 0.5 * k) if p.text == "z" else p.size
                cr.select_font_face("Adwaita Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(size)
                ext = cr.text_extents(p.text)
                cr.move_to(x - ext.width / 2 - ext.x_bearing, y)
                cr.text_path(p.text)
                src(cr, INK, fade * 0.9)
                cr.set_line_width(2.4)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.stroke_preserve()
                src(cr, p.color or WHITE, fade)
                cr.fill()
        cr.new_path()
