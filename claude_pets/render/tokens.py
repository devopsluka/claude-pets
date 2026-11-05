"""Design tokens for Claude Pets.

Three layers, as in the design-system skill: *primitive* raw values →
*semantic* purpose aliases → *component* tokens. The visual direction comes
from the design skill's brief for a pet/mascot product ("Mascot Modern": flat
shapes, rounded and friendly, warm palette — orange #F97316, green #4ADE80,
violet #8B5CF6; avoid cold/clinical).
"""

from .color import rgb

# --- primitive ---------------------------------------------------------------

PRIMITIVE = {
    "orange-300": "#FDBA74", "orange-400": "#FB923C", "orange-500": "#F97316", "orange-600": "#EA580C",
    "green-300": "#86EFAC", "green-400": "#4ADE80", "green-600": "#16A34A",
    "violet-300": "#C4B5FD", "violet-400": "#A78BFA", "violet-500": "#8B5CF6",
    "rose-300": "#FDA4AF", "rose-400": "#FB7185", "rose-500": "#F43F5E",
    "sky-300": "#7DD3FC", "sky-400": "#38BDF8",
    "amber-300": "#FCD34D", "amber-400": "#FBBF24",
    "cream-50": "#FFFAF0", "cream-100": "#FFF3E0", "cream-200": "#FFE5B4",
    "ink-950": "#17131B", "ink-900": "#211C27", "ink-800": "#2C2633", "ink-700": "#3A3342",
    "ink-600": "#4D4557", "ink-400": "#8F879B", "ink-300": "#B5AEC0", "ink-100": "#EDE8F2",
    "radius-s": 6, "radius-m": 10, "radius-l": 14, "radius-xl": 20,
    "space-1": 4, "space-2": 8, "space-3": 12, "space-4": 16, "space-5": 24,
    "font-family": "Adwaita Sans, Inter, Cantarell, sans-serif",
    "font-xs": 8.5, "font-s": 9.5, "font-m": 10.5, "font-l": 13,
}

# --- semantic ----------------------------------------------------------------

SEMANTIC = {
    "dark": {
        "surface": "ink-900", "surface-raised": "ink-800", "surface-sunken": "ink-950",
        "border": "ink-600", "text": "cream-50", "text-muted": "ink-300",
        "accent": "orange-500", "accent-text": "ink-950",
        "success": "green-400", "success-text": "ink-950",
        "danger": "rose-400", "danger-text": "ink-950",
        "info": "violet-400", "info-text": "ink-950",
        "warning": "amber-400", "warning-text": "ink-950",
    },
    "light": {
        "surface": "cream-50", "surface-raised": "cream-100", "surface-sunken": "cream-200",
        "border": "ink-300", "text": "ink-900", "text-muted": "ink-600",
        "accent": "orange-500", "accent-text": "ink-950",
        "success": "green-400", "success-text": "ink-950",
        "danger": "rose-400", "danger-text": "ink-950",
        "info": "violet-400", "info-text": "ink-950",
        "warning": "amber-400", "warning-text": "ink-950",
    },
}

# --- component ---------------------------------------------------------------

COMPONENT = {
    "bubble-say-bg": "surface", "bubble-say-fg": "text", "bubble-say-border": "border",
    "bubble-think-bg": "surface-raised", "bubble-think-fg": "text-muted", "bubble-think-border": "border",
    "bubble-alert-bg": "accent", "bubble-alert-fg": "accent-text", "bubble-alert-border": "accent",
    "bubble-success-bg": "success", "bubble-success-fg": "success-text", "bubble-success-border": "success",
    "bubble-error-bg": "danger", "bubble-error-fg": "danger-text", "bubble-error-border": "danger",
    "bubble-info-bg": "info", "bubble-info-fg": "info-text", "bubble-info-border": "info",
    "card-bg": "surface", "card-fg": "text", "card-muted": "text-muted", "card-border": "border",
    "card-track": "surface-sunken",
    "meter-energy": "warning", "meter-mood": "danger", "meter-focus": "info",
    "meter-context": "success", "meter-context-high": "accent", "meter-context-full": "danger",
}


class Theme:
    """Resolved tokens for one colour scheme (``dark`` or ``light``)."""

    def __init__(self, scheme="dark"):
        self.scheme = scheme if scheme in SEMANTIC else "dark"
        self._semantic = SEMANTIC[self.scheme]

    def hex(self, name):
        """Resolve a component / semantic / primitive token to its raw value."""
        seen = 0
        value = name
        while isinstance(value, str) and not value.startswith("#") and seen < 4:
            if value in COMPONENT:
                value = COMPONENT[value]
            elif value in self._semantic:
                value = self._semantic[value]
            elif value in PRIMITIVE:
                value = PRIMITIVE[value]
            else:
                break
            seen += 1
        return value

    def color(self, name):
        return rgb(self.hex(name))

    def num(self, name):
        return PRIMITIVE[name]

    @property
    def font(self):
        return PRIMITIVE["font-family"]


def as_json():
    """The token set in the design-system skill's three-layer JSON shape."""
    return {"primitive": PRIMITIVE, "semantic": SEMANTIC, "component": COMPONENT}


def gtk_css(scheme="dark"):
    """GTK3 CSS for the design studio, generated from the tokens."""
    t = Theme(scheme)
    h = t.hex
    return """
    .cp-window {{ background-color: {surface_sunken}; color: {text}; font-family: "Adwaita Sans", "Inter", "Cantarell", sans-serif; }}
    .cp-stage {{ background-color: {surface}; border-radius: {rl}px; border: 1px solid {border}; }}
    .cp-panel {{ background-color: {surface}; border-radius: {rl}px; border: 1px solid {border}; padding: {s3}px; }}
    .cp-title {{ font-size: 15pt; font-weight: 800; color: {text}; }}
    .cp-subtitle {{ font-size: 9.5pt; color: {muted}; }}
    .cp-section {{ font-size: 8.5pt; font-weight: 800; color: {muted}; letter-spacing: 1px; margin-top: {s2}px; }}
    .cp-chip {{ background-image: none; background-color: {raised}; color: {text}; border-radius: 999px; border: 1px solid {border}; padding: 4px 12px; box-shadow: none; text-shadow: none; font-weight: 600; min-height: 0; }}
    .cp-chip:hover {{ border-color: {accent}; }}
    .cp-chip:checked {{ background-color: {accent}; color: {accent_text}; border-color: {accent}; }}
    .cp-swatch {{ background-image: none; border-radius: 999px; border: 2px solid {border}; min-width: 26px; min-height: 26px; padding: 0; box-shadow: none; }}
    .cp-swatch:hover {{ border-color: {text}; }}
    .cp-swatch:checked {{ border-color: {text}; box-shadow: 0 0 0 2px {accent}; }}
    .cp-primary {{ background-image: none; background-color: {accent}; color: {accent_text}; border-radius: {rm}px; border: none; padding: 8px 18px; font-weight: 800; box-shadow: none; text-shadow: none; }}
    .cp-primary:hover {{ background-color: {accent_hover}; }}
    .cp-ghost {{ background-image: none; background-color: transparent; color: {text}; border-radius: {rm}px; border: 1px solid {border}; padding: 8px 14px; font-weight: 600; box-shadow: none; text-shadow: none; }}
    .cp-ghost:hover {{ border-color: {accent}; }}
    .cp-entry {{ background-image: none; background-color: {surface_sunken}; color: {text}; border-radius: {rm}px; border: 1px solid {border}; padding: 6px 10px; box-shadow: none; caret-color: {accent}; }}
    .cp-entry:focus {{ border-color: {accent}; }}
    .cp-list {{ background-color: transparent; }}
    .cp-list row {{ border-radius: {rm}px; padding: 6px 8px; color: {text}; }}
    .cp-list row:selected {{ background-color: {raised}; box-shadow: inset 3px 0 0 {accent}; }}
    .cp-stat {{ font-size: 9pt; color: {muted}; }}
    """.format(
        surface=h("surface"), surface_sunken=h("surface-sunken"), raised=h("surface-raised"),
        border=h("border"), text=h("text"), muted=h("text-muted"), accent=h("accent"),
        accent_text=h("accent-text"), accent_hover=PRIMITIVE["orange-400"],
        rl=PRIMITIVE["radius-l"], rm=PRIMITIVE["radius-m"], s2=PRIMITIVE["space-2"], s3=PRIMITIVE["space-3"],
    )
