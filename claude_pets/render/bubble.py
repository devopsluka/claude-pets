"""Speech bubbles and the hover status card (Pango text on Cairo)."""

import math

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from .color import INK, src  # noqa: E402
from .creature import ellipse, rounded_rect  # noqa: E402

_FONTS = {}

BUBBLE_FONT = "Adwaita Sans Semi-Bold 9.5"
STYLES = ("say", "think", "alert", "success", "error", "info")


def font(desc):
    cached = _FONTS.get(desc)
    if cached is None:
        cached = _FONTS[desc] = Pango.FontDescription.from_string(desc)
    return cached


def make_layout(cr, text, desc, max_width=None, lines=1):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(font(desc))
    if max_width:
        layout.set_width(int(max_width * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        if lines > 1:
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_height(-lines)
    layout.set_text(text, -1)
    return layout


def draw_bubble(cr, cx, bottom, text, style, theme, alpha=1.0, pop=1.0, max_width=210.0,
                min_x=None, max_x=None):
    """Draw a bubble whose tail tip sits at (cx, bottom). Returns its box."""
    if style not in STYLES:
        style = "say"
    layout = make_layout(cr, text, BUBBLE_FONT, max_width, lines=2)
    tw, th = layout.get_pixel_size()
    pad_x, pad_y, tail = 11.0, 6.5, 7.0
    w, h = tw + 2 * pad_x, th + 2 * pad_y
    x = cx - w / 2.0
    if min_x is not None:
        x = max(min_x, x)
    if max_x is not None:
        x = min(max_x - w, x)
    y = bottom - tail - h
    tip_x = min(max(cx, x + 14), x + w - 14)
    radius = min(13.0, h / 2.0)
    bg = theme.color("bubble-%s-bg" % style)
    fg = theme.color("bubble-%s-fg" % style)
    border = theme.color("bubble-%s-border" % style)

    cr.save()
    if pop != 1.0:
        cr.translate(cx, bottom)
        cr.scale(pop, pop)
        cr.translate(-cx, -bottom)
    if alpha < 1.0:
        cr.push_group()

    def body(offset=0.0):
        rounded_rect(cr, x, y + offset, w, h, radius)
        if style == "think":
            ellipse(cr, tip_x + 1, y + h + 3.2 + offset, 3.0, 2.6)
            ellipse(cr, tip_x - 2.5, y + h + 8.0 + offset, 1.8, 1.6)
        else:
            cr.new_sub_path()
            cr.move_to(tip_x - 6.5, y + h - 1 + offset)
            cr.line_to(tip_x, y + h + tail + offset)
            cr.line_to(tip_x + 6.5, y + h - 1 + offset)
            cr.close_path()

    body(2.0)
    src(cr, INK, 0.28)
    cr.fill()
    body()
    src(cr, border)
    cr.set_line_width(2.4)
    cr.stroke_preserve()
    src(cr, bg)
    cr.fill()
    cr.move_to(x + pad_x, y + pad_y)
    src(cr, fg)
    PangoCairo.show_layout(cr, layout)
    cr.new_path()
    if alpha < 1.0:
        cr.pop_group_to_source()
        cr.paint_with_alpha(max(0.0, alpha))
    cr.restore()
    return (x, y, w, h + tail)


def _meter(cr, theme, x, y, w, label, value, token, text=None):
    cr.move_to(x, y)
    src(cr, theme.color("card-muted"))
    PangoCairo.show_layout(cr, make_layout(cr, label, "Adwaita Sans Bold 7.5"))
    bar_x, bar_w, bar_h = x + 52, w - 52 - (34 if text else 0), 6.0
    rounded_rect(cr, bar_x, y + 4.5, bar_w, bar_h, 3)
    src(cr, theme.color("card-track"))
    cr.fill()
    value = max(0.0, min(1.0, value))
    if value > 0.02:
        rounded_rect(cr, bar_x, y + 4.5, max(bar_h, bar_w * value), bar_h, 3)
        src(cr, theme.color(token))
        cr.fill()
    if text:
        layout = make_layout(cr, text, "Adwaita Sans Bold 7.5")
        tw, _ = layout.get_pixel_size()
        cr.move_to(x + w - tw, y)
        src(cr, theme.color("card-fg"))
        PangoCairo.show_layout(cr, layout)
    cr.new_path()


CARD_W, CARD_H = 252, 176


def draw_card(cr, x, y, info, theme, alpha=1.0):
    """The hover card: who this pet is, what its session is doing and feeling."""
    w, h = CARD_W, CARD_H
    cr.save()
    if alpha < 1.0:
        cr.push_group()
    rounded_rect(cr, x + 1, y + 3, w - 2, h - 2, 14)
    src(cr, INK, 0.3)
    cr.fill()
    rounded_rect(cr, x + 1, y + 1, w - 2, h - 4, 14)
    src(cr, theme.color("card-bg"), 0.97)
    cr.fill_preserve()
    src(cr, theme.color("card-border"))
    cr.set_line_width(1.4)
    cr.stroke()

    pad = 13
    inner = w - 2 * pad
    ty = y + 11
    # name + level
    name = make_layout(cr, info.get("name", "Pet"), "Adwaita Sans Heavy 11.5", inner - 70)
    cr.move_to(x + pad, ty)
    src(cr, theme.color("card-fg"))
    PangoCairo.show_layout(cr, name)
    badge = make_layout(cr, info.get("badge", ""), "Adwaita Sans Bold 8")
    bw, bh = badge.get_pixel_size()
    if bw:
        rounded_rect(cr, x + w - pad - bw - 12, ty + 1, bw + 12, bh + 4, (bh + 4) / 2)
        src(cr, theme.color("accent"))
        cr.fill()
        cr.move_to(x + w - pad - bw - 6, ty + 3)
        src(cr, theme.color("accent-text"))
        PangoCairo.show_layout(cr, badge)
    ty += 20
    sub = make_layout(cr, info.get("subtitle", ""), "Adwaita Sans 8.5", inner)
    cr.move_to(x + pad, ty)
    src(cr, theme.color("card-muted"))
    PangoCairo.show_layout(cr, sub)
    ty += 18
    cr.new_path()
    cr.move_to(x + pad, ty)
    cr.line_to(x + w - pad, ty)
    src(cr, theme.color("card-border"), 0.7)
    cr.set_line_width(1)
    cr.stroke()
    ty += 7
    status = make_layout(cr, info.get("status", ""), "Adwaita Sans Semi-Bold 9.5", inner)
    cr.move_to(x + pad, ty)
    src(cr, theme.color("card-fg"))
    PangoCairo.show_layout(cr, status)
    ty += 17
    feeling = make_layout(cr, info.get("feeling", ""), "Adwaita Sans Italic 8.5", inner)
    cr.move_to(x + pad, ty)
    src(cr, theme.color("card-muted"))
    PangoCairo.show_layout(cr, feeling)
    ty += 19
    _meter(cr, theme, x + pad, ty, inner, "ENERGY", info.get("energy", 0.0), "meter-energy")
    ty += 13
    _meter(cr, theme, x + pad, ty, inner, "MOOD", info.get("mood", 0.0), "meter-mood")
    ty += 13
    _meter(cr, theme, x + pad, ty, inner, "FOCUS", info.get("focus", 0.0), "meter-focus")
    ty += 13
    ctx = info.get("context")
    if ctx is None:
        _meter(cr, theme, x + pad, ty, inner, "CONTEXT", 0.0, "meter-context", "–")
    else:
        token = "meter-context-full" if ctx >= 0.9 else "meter-context-high" if ctx >= 0.75 else "meter-context"
        _meter(cr, theme, x + pad, ty, inner, "CONTEXT", ctx, token, "%d%%" % round(ctx * 100))
    ty += 16
    foot = make_layout(cr, info.get("footer", ""), "Adwaita Sans 8", inner)
    cr.move_to(x + pad, ty)
    src(cr, theme.color("card-muted"))
    PangoCairo.show_layout(cr, foot)
    cr.new_path()
    if alpha < 1.0:
        cr.pop_group_to_source()
        cr.paint_with_alpha(max(0.0, alpha))
    cr.restore()


def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * math.pow(t - 1, 3) + c1 * math.pow(t - 1, 2)
