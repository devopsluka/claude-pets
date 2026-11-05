"""Small colour helpers. Colours are ``(r, g, b)`` float tuples in 0..1."""

from functools import lru_cache

WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)
#: Outlines are mixed towards this warm plum instead of pure black so the
#: pets read as soft stickers, not as hard cartoons.
INK = (0.16, 0.11, 0.20)


@lru_cache(maxsize=512)
def rgb(value):
    """Parse ``#rgb`` / ``#rrggbb`` (or pass a tuple through)."""
    if isinstance(value, tuple):
        return value
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError("bad colour: %r" % (value,))
    return (int(text[0:2], 16) / 255.0, int(text[2:4], 16) / 255.0, int(text[4:6], 16) / 255.0)


def to_hex(color):
    r, g, b = (max(0, min(255, round(c * 255))) for c in color)
    return "#%02X%02X%02X" % (r, g, b)


def is_hex(value):
    try:
        rgb(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def mix(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def lighten(color, t):
    return mix(color, WHITE, t)


def darken(color, t):
    return mix(color, BLACK, t)


def luminance(color):
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def outline_of(color):
    """Outline colour for a fill: same hue, pulled towards ink."""
    amount = 0.62 if luminance(color) > 0.25 else 0.45
    return mix(color, INK, amount)


def src(cr, color, alpha=1.0):
    cr.set_source_rgba(color[0], color[1], color[2], alpha)
