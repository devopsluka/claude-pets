"""Procedural pet renderer (Cairo).

Every pet is drawn from parts on one shared chibi rig, so a species is just a
recipe (ears, tail, muzzle, markings) and a pose is just numbers. Units are
"pet units": the origin is the spot on the ground between the feet, +x is
right, +y is down; a standing pet is about 60 wide and 80-95 tall.
"""

import math
from dataclasses import dataclass, field
from functools import lru_cache

import cairo

from .color import INK, WHITE, darken, lighten, luminance, mix, outline_of, rgb, src

TAU = math.tau
LW = 2.3                       # outline width

HEAD_CY, HEAD_RX, HEAD_RY = -48.0, 30.0, 26.0
BODY_CY, BODY_RX, BODY_RY = -17.0, 19.0, 16.5
GRAB_Y = -72.0                 # scruff: the point a dragged pet hangs from

MOUTH_DARK = rgb("#5B2B3C")
TONGUE = rgb("#FF8FA3")
SILVER = rgb("#DDE2EA")
SILVER_D = rgb("#B9C0CC")
GOLD = rgb("#FBBF24")
TEAR = rgb("#8FD3FF")
TEAR_D = rgb("#4A90C2")
PAPER = rgb("#FFFDF7")


# ----------------------------------------------------------------------------
# design + pose
# ----------------------------------------------------------------------------

@dataclass
class Design:
    """How one pet looks. Everything here is user-editable in the studio."""

    species: str = "cat"
    fur: str = "#F9913B"
    belly: str = "#FFE2BF"
    accent: str = "#8B5CF6"      # accessories
    extra: str = ""              # species detail colour (socks, gills, horns, beak, glow)
    eye: str = "#2A2238"
    cheek: str = "#FF8FA3"
    pattern: str = "plain"
    accessory: str = "none"

    def key(self):
        return (self.species, self.fur, self.belly, self.accent, self.extra, self.eye,
                self.cheek, self.pattern, self.accessory)


@dataclass
class Pose:
    """Everything that changes from frame to frame."""

    t: float = 0.0               # animation clock, seconds
    facing: float = 0.0          # -1 looking left .. +1 looking right
    tail_side: float = -1.0      # which side the tail hangs on
    bob: float = 0.0             # whole-body vertical offset (+ down)
    lift: float = 0.0            # airborne height (+ up)
    squash: float = 0.0          # + squashed, - stretched
    lean: float = 0.0            # whole-body rotation, radians
    breath: float = 0.0          # -1..1 breathing phase
    sit: float = 0.0             # 0 standing .. 1 sitting
    lie: float = 0.0             # 0 .. 1 loafing / asleep
    head_dx: float = 0.0
    head_dy: float = 0.0
    head_tilt: float = 0.0
    look: tuple = (0.0, 0.0)     # gaze, -1..1 each
    eye: str = "open"            # open happy closed wide sparkle heart spiral x squeeze sleepy angry sad
    eye_open: float = 1.0        # blink: 1 open .. 0 shut
    mouth: str = "smile"         # smile cat grin o flat frown wavy tongue teeth yawn none
    mouth_open: float = 1.0
    brow: str = ""               # "" angry sad raised
    blush: float = 0.5
    arm_l: float = 0.35          # arm angle: 0 hangs straight down, ~2.6 raised high
    arm_r: float = 0.35
    arm_fwd_l: float = 0.0       # 0..1 reach towards the front/centre
    arm_fwd_r: float = 0.0
    foot_l: tuple = (0.0, 0.0)   # walk-cycle offsets
    foot_r: tuple = (0.0, 0.0)
    tail: float = 0.0            # -1..1 sway
    ear: float = 0.0             # -1 droopy .. +1 perked
    prop: str = ""               # laptop book magnifier clipboard mug sign flag terminal globe gear
    prop_t: float = 0.0          # prop animation clock
    prop_text: str = "!"
    prop_side: float = 1.0       # which side external props sit on
    hat: str = ""                # contextual: party hardhat nightcap headphones
    glasses: bool = False        # contextual reading glasses
    marks: frozenset = frozenset()   # sweat tear anger gloom bandage thermo cloud dizzy
    belly: float = 0.0           # 0..1 bloat (context window filling up)
    held: bool = False           # being carried by the pointer
    dangle: float = 0.0          # pendulum angle while held
    cache_key: tuple = None      # set when this exact picture recurs (looping poses)
    hand_l: tuple = None         # explicit hand position (pet units) overriding the arm angle
    hand_r: tuple = None
    item: str = ""               # small signature item: joint bulb bills pigeon
    item_at: str = "hand"        # hand | hand_l | mouth | over
    item_glow: float = 0.0       # ember / bulb brightness, 0..1
    flash: float = 0.0           # white flash over the silhouette (electrocution), 0..1
    shock: bool = False          # hair standing on end


# ----------------------------------------------------------------------------
# species
# ----------------------------------------------------------------------------

SPECIES = {
    "cat": dict(label="Cat", ears="cat", tail="cat", nose="tri", mouth="cat", whiskers=True,
                patterns=("plain", "tabby", "socks", "spots", "tuxedo")),
    "dog": dict(label="Dog", ears="flop", tail="dog", nose="oval", mouth="smile", muzzle=True,
                patterns=("plain", "patch", "socks", "spots")),
    "fox": dict(label="Fox", ears="fox", tail="fox", nose="tri", mouth="cat", mask=True, dark_limbs=True,
                nose_dark=True, patterns=("plain",)),
    "bunny": dict(label="Bunny", ears="bunny", tail="puff", nose="tri", mouth="cat", whiskers=True,
                  patterns=("plain", "spots", "socks", "patch")),
    "bear": dict(label="Bear", ears="round", tail="nub", nose="oval", mouth="smile", muzzle=True,
                 patterns=("plain", "socks")),
    "panda": dict(label="Panda", ears="round", tail="nub", nose="oval", mouth="smile", muzzle=True,
                  eye_patches=True, dark_limbs=True, dark_ears=True, patterns=("plain",)),
    "penguin": dict(label="Penguin", ears="none", tail="none", nose="beak", mouth="beak", face_mask=True,
                    flippers=True, body=(18.5, 18.5, 0.56, 0.72), patterns=("plain",)),
    "frog": dict(label="Frog", ears="bumps", tail="none", nose="dots", mouth="smile", wide_mouth=1.9,
                 head=(31.0, 23.0, 0.62, 0.72), eye_y=-15.0, eye_dx=14.0, patterns=("plain", "spots")),
    "axolotl": dict(label="Axolotl", ears="gills", tail="fin", nose="none", mouth="smile", wide_mouth=1.6,
                    head=(31.0, 24.5, 0.62, 0.74), eye_dx=15.5, eye_scale=0.82, patterns=("plain", "spots")),
    "dragon": dict(label="Dragon", ears="horns", tail="dragon", nose="dots", mouth="smile", wings=True,
                   plates=True, fang=True, patterns=("plain", "spots")),
    "robot": dict(label="Robot", ears="antenna", tail="cable", nose="none", mouth="smile", visor=True,
                  head=(28.0, 23.5, 0.86, 0.86), body=(17.5, 15.5, 0.84, 0.84), led=True,
                  patterns=("plain",)),
    "ghost": dict(label="Ghost", ears="none", tail="none", nose="none", mouth="smile", rig="ghost",
                  patterns=("plain",)),
}
SPECIES.update({
    # Legends: human caricatures. Colour slots are outfit / skin / hair / signature colour.
    "tyson": dict(label="Mike Tyson", human=True, hair="buzz", facial="none", outfit="boxer", gloves=True,
                  tattoo=True, brow_w=2.8, ears="none", tail="none", nose="human", mouth="smile",
                  head=(28.5, 25.0, 0.64, 0.74), body=(20.0, 16.5, 0.62, 0.70), eye_y=2.0, eye_dx=11.5,
                  eye_scale=0.9, patterns=("plain",)),
    "snoop": dict(label="Snoop Dogg", human=True, hair="braids", facial="goatee", outfit="hoodie", shades=True,
                  brow_w=1.8, shoes="#F4F4F6", ears="none", tail="none", nose="human", mouth="smile",
                  head=(25.0, 26.5, 0.60, 0.66), body=(17.0, 16.5, 0.58, 0.68), eye_y=1.0, eye_dx=10.5,
                  eye_scale=0.9, patterns=("plain",)),
    "pablo": dict(label="Pablo Escobar", human=True, hair="curly", facial="mustache", outfit="shirt", brow_w=2.8,
                  ears="none", tail="none", nose="human", mouth="smile", head=(30.0, 25.5, 0.62, 0.80),
                  body=(21.0, 17.0, 0.58, 0.74), eye_y=1.5, eye_dx=12.0, eye_scale=0.9, patterns=("plain",)),
    "einstein": dict(label="Albert Einstein", human=True, hair="wild", facial="bushy", outfit="sweater",
                     brow_w=2.8, ears="none", tail="none", nose="human", mouth="smile",
                     head=(28.0, 25.0, 0.62, 0.72), eye_y=2.5, eye_dx=11.5, eye_scale=0.95, patterns=("plain",)),
    "tesla": dict(label="Nikola Tesla", human=True, hair="slick", facial="thin", outfit="suit", brow_w=1.9,
                  ears="none", tail="none", nose="human", mouth="smile", head=(26.5, 25.5, 0.60, 0.66),
                  body=(17.5, 16.5, 0.58, 0.68), eye_y=2.0, eye_dx=11.0, eye_scale=0.9, patterns=("plain",)),
})
SPECIES_ORDER = ("cat", "dog", "fox", "bunny", "bear", "panda", "penguin", "frog", "axolotl",
                 "dragon", "robot", "ghost")
LEGENDS = ("tyson", "snoop", "pablo", "einstein", "tesla")
ALL_SPECIES = SPECIES_ORDER + LEGENDS
LEGEND_NAMES = {"tyson": "Mike", "snoop": "Snoop", "pablo": "Pablo", "einstein": "Albert", "tesla": "Nikola"}
#: the colour of each legend's signature: gloves, chain, shirt print, bulb, lightning
SIGNATURE_ACCENT = {"tyson": "#E0282E", "snoop": "#FBBF24", "pablo": "#3B82F6", "einstein": "#FBBF24",
                    "tesla": "#7DD3FC"}

PATTERNS = ("plain", "tabby", "spots", "socks", "patch", "tuxedo")
ACCESSORIES = ("none", "bowtie", "scarf", "glasses", "crown", "beanie", "flower", "headphones",
               "wizard", "cap", "bandana")

#: (fur, belly, extra) presets per species; the first one is the species default.
COATS = {
    "cat": (("#F9913B", "#FFE2BF", ""), ("#A7AFBD", "#EEF1F6", ""), ("#4B4856", "#8D8A9C", ""),
            ("#F6E3C5", "#FFF8EA", ""), ("#C98B5E", "#F3D9BF", "")),
    "dog": (("#D9A066", "#FBE9D0", "#8A5A3C"), ("#F4E4C9", "#FFF9EE", "#C89B6D"),
            ("#8C6A56", "#E8D2BF", "#5C4336"), ("#F1F1F4", "#FFFFFF", "#3F3D4A")),
    "fox": (("#F27F3D", "#FFF4E6", "#4A2F2A"), ("#E9EDF4", "#FFFFFF", "#56607A"),
            ("#C7553A", "#FFE9D6", "#3A2422")),
    "bunny": (("#F4EEF0", "#FFFFFF", "#FFB3C1"), ("#D9C2A7", "#FBF0E2", "#FFB3C1"),
              ("#B9A2F2", "#EFE8FF", "#FFB3C1"), ("#9AA3B2", "#E8ECF2", "#FFB3C1")),
    "bear": (("#A9744F", "#EBCFB2", ""), ("#F3E3C7", "#FFF8EC", ""), ("#6B5A52", "#C9B8AE", ""),
             ("#F7A8B8", "#FFE3EA", "")),
    "panda": (("#F7F7F9", "#FFFFFF", "#3B3945"), ("#FBEFE0", "#FFFFFF", "#8A4B2F")),
    "penguin": (("#414F6E", "#FFFFFF", "#FFB238"), ("#3A3945", "#FFFFFF", "#FFB238"),
                ("#5D7FB8", "#F2F8FF", "#FF9F6B")),
    "frog": (("#8CCB6B", "#EAF6CF", ""), ("#5FC9A8", "#DCF7EC", ""), ("#E9C46A", "#FFF4CF", "")),
    "axolotl": (("#FFB3C7", "#FFE6EC", "#FF6F9C"), ("#C9B6FF", "#F0EAFF", "#8B5CF6"),
                ("#FFF1D6", "#FFFFFF", "#FF9F6B"), ("#8FD9D0", "#E3F8F5", "#2FA89B")),
    "dragon": (("#5CC4B0", "#FFF0BF", "#F97316"), ("#9A7CF0", "#FFE9C7", "#FB7185"),
               ("#F2705C", "#FFE7B8", "#8B5CF6"), ("#6BA8F2", "#EAF4FF", "#FBBF24")),
    "robot": (("#C9D1DC", "#EEF2F7", "#4ADE80"), ("#FDBA74", "#FFF1DD", "#38BDF8"),
              ("#A78BFA", "#EDE7FF", "#FCD34D"), ("#7DD3FC", "#EAF8FF", "#FB7185")),
    "ghost": (("#F5F2FF", "#FFFFFF", ""), ("#D9F7EE", "#FFFFFF", ""), ("#FFE3EC", "#FFFFFF", "")),
    # legends: (outfit, skin, hair)
    "tyson": (("#26252E", "#B5764A", "#2A2019"), ("#F4F4F6", "#B5764A", "#2A2019"), ("#B91C1C", "#B5764A", "#2A2019")),
    "snoop": (("#3B6FD9", "#8A5A3C", "#1E1A1A"), ("#7C4DCC", "#8A5A3C", "#1E1A1A"), ("#2F9E6E", "#8A5A3C", "#1E1A1A")),
    "pablo": (("#F3F1EA", "#E0A67A", "#2B211C"), ("#F7B8C4", "#E0A67A", "#2B211C"), ("#9CC9EE", "#E0A67A", "#2B211C")),
    "einstein": (("#8A6A4F", "#F1C9A5", "#EDEDF2"), ("#6F7C8A", "#F1C9A5", "#EDEDF2"), ("#7A8F5A", "#F1C9A5", "#EDEDF2")),
    "tesla": (("#2E3440", "#F3D6BE", "#221B18"), ("#3A2F5B", "#F3D6BE", "#221B18"), ("#4A3B2F", "#F3D6BE", "#221B18")),
}

ACCENTS = ("#8B5CF6", "#F97316", "#4ADE80", "#38BDF8", "#FB7185", "#FBBF24")


def default_design(species="cat", coat=0, accent=0):
    fur, belly, extra = COATS[species][coat % len(COATS[species])]
    signature = SIGNATURE_ACCENT.get(species) if accent == 0 else None
    return Design(species=species, fur=fur, belly=belly, extra=extra,
                  accent=signature or ACCENTS[accent % len(ACCENTS)])


class _Skin:
    """Colours derived from a design (cached per design)."""

    def __init__(self, design):
        spec = SPECIES.get(design.species, SPECIES["cat"])
        self.fur = rgb(design.fur)
        self.belly = rgb(design.belly)
        self.accent = rgb(design.accent)
        self.extra = rgb(design.extra) if design.extra else darken(self.fur, 0.3)
        self.eye = rgb(design.eye)
        self.cheek = rgb(design.cheek)
        self.line = outline_of(self.fur)
        self.shade = darken(self.fur, 0.16)
        self.light = lighten(self.fur, 0.25)
        self.stripe = mix(self.fur, INK, 0.3)
        dark = spec.get("dark_limbs")
        self.limb = self.extra if dark else self.fur
        self.limb_line = outline_of(self.limb)
        if design.pattern == "socks" and not dark:
            self.limb = self.belly
            self.limb_line = outline_of(mix(self.belly, self.fur, 0.5))
        self.ear = self.extra if spec.get("dark_ears") else self.fur
        self.inner = mix(self.cheek, self.belly, 0.35)
        self.nose = INK if (spec.get("nose_dark") or spec.get("nose") == "oval") else darken(self.cheek, 0.08)
        self.accent_line = outline_of(self.accent)
        if spec.get("human"):
            self.skin = self.belly
            self.skin_line = outline_of(self.skin)
            self.hair = self.extra
            self.hair_line = outline_of(self.hair)
            if spec.get("outfit") == "boxer":
                self.limb, self.limb_line = self.skin, self.skin_line
            else:
                self.limb, self.limb_line = self.fur, self.line
            self.shoe = rgb(spec.get("shoes", "#2A2630"))


@lru_cache(maxsize=128)
def _skin_cached(key):
    return _Skin(Design(*key))


# ----------------------------------------------------------------------------
# path helpers
# ----------------------------------------------------------------------------

def ellipse(cr, cx, cy, rx, ry, rot=0.0):
    cr.save()
    cr.translate(cx, cy)
    if rot:
        cr.rotate(rot)
    cr.scale(max(rx, 0.01), max(ry, 0.01))
    cr.new_sub_path()
    cr.arc(0, 0, 1, 0, TAU)
    cr.close_path()
    cr.restore()


def blob(cr, cx, cy, rx, ry, kt=0.5523, kb=0.5523, rot=0.0):
    """Ellipse whose top/bottom halves can be made squarer (k -> 1)."""
    cr.save()
    cr.translate(cx, cy)
    if rot:
        cr.rotate(rot)
    cr.new_sub_path()
    cr.move_to(0, -ry)
    cr.curve_to(kt * rx, -ry, rx, -kt * ry, rx, 0)
    cr.curve_to(rx, kb * ry, kb * rx, ry, 0, ry)
    cr.curve_to(-kb * rx, ry, -rx, kb * ry, -rx, 0)
    cr.curve_to(-rx, -kt * ry, -kt * rx, -ry, 0, -ry)
    cr.close_path()
    cr.restore()


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2.0, h / 2.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -TAU / 4, 0)
    cr.arc(x + w - r, y + h - r, r, 0, TAU / 4)
    cr.arc(x + r, y + h - r, r, TAU / 4, TAU / 2)
    cr.arc(x + r, y + r, r, TAU / 2, TAU * 3 / 4)
    cr.close_path()


def paint(cr, fill, line=None, lw=LW, alpha=1.0):
    """Fill and/or outline the current path."""
    if fill is not None:
        src(cr, fill, alpha)
        if line is None:
            cr.fill()
            return
        cr.fill_preserve()
    if line is not None:
        src(cr, line, alpha)
        cr.set_line_width(lw)
        cr.stroke()
    else:
        cr.new_path()


def _trace(cr, pts):
    cr.new_path()
    cr.move_to(*pts[0])
    if len(pts) == 4:
        cr.curve_to(pts[1][0], pts[1][1], pts[2][0], pts[2][1], pts[3][0], pts[3][1])
    else:
        for point in pts[1:]:
            cr.line_to(*point)


def tube(cr, pts, width, fill, line, lw=LW):
    """A fat outlined stroke along a line / cubic bezier (tails, arms, stalks)."""
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    _trace(cr, pts)
    src(cr, line)
    cr.set_line_width(width + 2 * lw)
    cr.stroke()
    _trace(cr, pts)
    src(cr, fill)
    cr.set_line_width(width)
    cr.stroke()


def stroke(cr, color, lw=1.9, alpha=1.0):
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    src(cr, color, alpha)
    cr.set_line_width(lw)
    cr.stroke()


def star_path(cr, cx, cy, r_out, r_in, points=4, rot=0.0):
    cr.new_sub_path()
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * TAU / (points * 2) - TAU / 4
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()


def heart_path(cr, cx, cy, size):
    s = size
    cr.new_sub_path()
    cr.move_to(cx, cy + s * 0.9)
    cr.curve_to(cx - s * 1.5, cy - s * 0.1, cx - s * 0.75, cy - s * 1.15, cx, cy - s * 0.35)
    cr.curve_to(cx + s * 0.75, cy - s * 1.15, cx + s * 1.5, cy - s * 0.1, cx, cy + s * 0.9)
    cr.close_path()


def drop_path(cr, cx, cy, size):
    s = size
    cr.new_sub_path()
    cr.move_to(cx, cy - s * 1.5)
    cr.curve_to(cx + s * 1.1, cy - s * 0.1, cx + s * 0.9, cy + s, cx, cy + s)
    cr.curve_to(cx - s * 0.9, cy + s, cx - s * 1.1, cy - s * 0.1, cx, cy - s * 1.5)
    cr.close_path()


# ----------------------------------------------------------------------------
# painter
# ----------------------------------------------------------------------------

class _Painter:
    def __init__(self, cr, design, pose, flat=False):
        self.cr = cr
        self.flat = flat               # silhouette pass: skip interior detail
        self.d = design
        self.p = pose
        self.spec = SPECIES.get(design.species, SPECIES["cat"])
        self.k = _skin_cached(design.key())
        hx = self.spec.get("head", (HEAD_RX, HEAD_RY, 0.60, 0.74))
        bx = self.spec.get("body", (BODY_RX, BODY_RY, 0.58, 0.70))
        self.head_rx, self.head_ry, self.head_kt, self.head_kb = hx
        p = pose
        self.body_cy = BODY_CY + p.sit * 4.0 + p.lie * 5.5
        self.body_rx = bx[0] * (1 + p.lie * 0.24 + p.sit * 0.05) * (1 + p.belly * 0.13)
        self.body_ry = bx[1] * (1 - p.lie * 0.26) * (1 + p.belly * 0.05) * (1 + p.breath * 0.025)
        self.body_k = (bx[2], bx[3])
        self.head_cx = p.head_dx
        self.head_cy = HEAD_CY + p.sit * 4.0 + p.lie * 13.0 + p.head_dy - p.breath * 0.7
        self.eye_y = self.spec.get("eye_y", 3.0)
        self.eye_dx = self.spec.get("eye_dx", 12.5)
        self.eye_scale = self.spec.get("eye_scale", 1.0)
        self.led = bool(self.spec.get("led"))
        self.human = bool(self.spec.get("human"))
        self.hands = {}                # side -> where that hand ended up (for held items)

    # -- top level ------------------------------------------------------

    def draw(self, shadow=True):
        cr, p = self.cr, self.p
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        if shadow:
            self.shadow()
        self.external_props()
        cr.save()
        if p.held:
            cr.translate(0, GRAB_Y)
            cr.rotate(p.dangle)
            cr.translate(0, -GRAB_Y)
        cr.translate(0, p.bob - p.lift)
        if p.lean:
            cr.rotate(p.lean)
        if p.squash:
            cr.scale(1 + 0.22 * p.squash, 1 - 0.22 * p.squash)
        if self.spec.get("rig") == "ghost":
            self.ghost()
        else:
            self.tail()
            if self.spec.get("wings"):
                self.wings()
            self.feet()
            self.body()
            if p.prop == "belt":
                _human.belt(self)
            chin = self.head_cy + self.head_ry - 2.0
            arms = [(side, angle, fwd, target, (target[1] < chin) if target is not None else angle >= 1.25)
                    for side, angle, fwd, target in ((-1, p.arm_l, p.arm_fwd_l, p.hand_l),
                                                     (1, p.arm_r, p.arm_fwd_r, p.hand_r))]
            for side, angle, fwd, target, raised in arms:
                if not raised:
                    self.arm(side, angle, fwd, target)
            self.neck_accessory()
            self.head()
            self.held_props()
            for side, angle, fwd, target, raised in arms:
                if raised:
                    self.arm(side, angle, fwd, target)
            if p.item:
                _human.item(self)
        cr.restore()
        self.overhead_marks()

    def shadow(self):
        cr, p = self.cr, self.p
        if p.held:
            return
        lift = max(0.0, p.lift)
        grow = 1 + self.p.lie * 0.2
        ellipse(cr, 0, 1.5, 24 * grow * max(0.35, 1 - lift / 70.0), 4.6 * max(0.35, 1 - lift / 70.0))
        src(cr, INK, 0.22 * max(0.25, 1 - lift / 90.0))
        cr.fill()

    # -- body parts -----------------------------------------------------

    def tail(self):
        cr, p, k = self.cr, self.p, self.k
        kind = self.spec.get("tail", "none")
        if kind == "none":
            return
        sd = p.tail_side
        by = self.body_cy
        sway = p.tail
        low = p.lie * 6 + p.sit * 2
        if kind == "cat":
            pts = ((sd * 11, by + 9 + low * 0.3), (sd * 33, by + 13 + low * 0.2),
                   (sd * 39 + sway * 5, by - 12 + low), (sd * 27 + sway * 9, by - 22 + low))
            tube(cr, pts, 6.4, k.fur, k.line)
            if self.d.pattern in ("socks", "tuxedo"):
                tip = pts[3]
                ellipse(cr, tip[0], tip[1], 3.2, 3.2)
                paint(cr, k.belly)
        elif kind == "dog":
            pts = ((sd * 13, by + 5), (sd * 25, by + 3), (sd * 28 + sway * 6, by - 9),
                   (sd * 22 + sway * 9, by - 13))
            tube(cr, pts, 5.6, k.fur, k.line)
        elif kind == "fox":
            cr.save()
            cr.translate(sd * 13, by + 8 + low * 0.4)
            cr.rotate(sd * (0.95 + sway * 0.16))
            blob(cr, 0, -15, 9.5, 17, 0.62, 0.5)
            cr.save()
            cr.clip()
            src(cr, k.fur)
            cr.paint()
            ellipse(cr, 0, -29, 10, 9)
            paint(cr, k.belly)
            cr.restore()
            blob(cr, 0, -15, 9.5, 17, 0.62, 0.5)
            paint(cr, None, k.line)
            cr.restore()
        elif kind == "puff":
            ellipse(cr, sd * 17.5, by + 8, 6.2, 6.0)
            paint(cr, k.belly, outline_of(mix(k.belly, k.fur, 0.5)))
        elif kind == "nub":
            ellipse(cr, sd * 17, by + 9, 4.3, 4.3)
            paint(cr, k.ear, outline_of(k.ear))
        elif kind == "fin":
            cr.save()
            cr.translate(sd * 12, by + 8 + low * 0.4)
            cr.rotate(sd * (1.2 + sway * 0.14))
            blob(cr, 0, -13, 7.5, 15, 0.6, 0.5)
            paint(cr, k.fur, k.line)
            blob(cr, 0, -13, 3.6, 10.5, 0.6, 0.5)
            paint(cr, k.extra, None, alpha=0.75)
            cr.restore()
        elif kind == "dragon":
            pts = ((sd * 11, by + 9), (sd * 30, by + 14), (sd * 36 + sway * 4, by + 2),
                   (sd * 35 + sway * 7, by - 10))
            tube(cr, pts, 7.2, k.fur, k.line)
            tx, ty = pts[3]
            cr.save()
            cr.translate(tx, ty)
            cr.rotate(sd * 0.2 + sway * 0.25)
            cr.new_path()
            cr.move_to(0, -9)
            cr.line_to(6.5, 1.5)
            cr.line_to(-6.5, 1.5)
            cr.close_path()
            paint(cr, k.extra, outline_of(k.extra))
            cr.restore()
        elif kind == "cable":
            pts = ((sd * 12, by + 6), (sd * 26, by + 14), (sd * 34 + sway * 3, by + 2),
                   (sd * 30 + sway * 5, by - 6))
            tube(cr, pts, 2.2, darken(k.fur, 0.35), k.line, lw=1.2)
            tx, ty = pts[3]
            rounded_rect(cr, tx - 3.2, ty - 6, 6.4, 6.4, 1.6)
            paint(cr, k.extra, outline_of(k.extra), lw=1.5)

    def wings(self):
        cr, k, p = self.cr, self.k, self.p
        flap = math.sin(p.t * 9.0) * 0.18 if p.lift > 2 else math.sin(p.t * 2.6) * 0.05
        for side in (-1, 1):
            cr.save()
            cr.translate(side * 14, self.body_cy - 9)
            cr.rotate(side * (0.25 + flap))
            cr.new_path()
            cr.move_to(0, 0)
            cr.curve_to(side * 8, -16, side * 20, -18, side * 24, -10)
            cr.curve_to(side * 20, -9, side * 18, -6, side * 18, -2)
            cr.curve_to(side * 14, -4, side * 12, -2, side * 11, 2)
            cr.curve_to(side * 8, 0, side * 5, 1, 0, 4)
            cr.close_path()
            paint(cr, k.extra, outline_of(k.extra))
            cr.restore()

    def feet(self):
        cr, p, k = self.cr, self.p, self.k
        if self.spec.get("flippers"):
            fill, line = k.extra, outline_of(k.extra)
        elif self.human:
            fill, line = k.shoe, outline_of(k.shoe)
        else:
            fill, line = k.limb, k.limb_line
        spread = 9.5 + p.sit * 5.0 + p.lie * 3.0
        tuck = min(max(p.lift, 0.0), 8.0) * 0.3
        for side, off in ((-1, p.foot_l), (1, p.foot_r)):
            cx = side * spread + off[0]
            cy = -3.2 + p.sit * 0.6 + off[1] - tuck
            if self.led:
                rounded_rect(cr, cx - 7.5, cy - 4.2, 15, 8.4, 3.2)
            else:
                ellipse(cr, cx, cy, 8.0 - p.lie, 5.2 + p.sit * 0.8)
            paint(cr, fill, line)

    def body_path(self):
        blob(self.cr, 0, self.body_cy, self.body_rx, self.body_ry, self.body_k[0], self.body_k[1])

    def body(self):
        cr, p, k, d = self.cr, self.p, self.k, self.d
        if self.human:
            _human.body(self)
            return
        if self.flat:
            self.body_path()
            paint(cr, k.fur, k.line)
            return
        self.body_path()
        cr.save()
        cr.clip()
        src(cr, k.fur)
        cr.paint()
        by = self.body_cy
        if self.spec.get("flippers"):
            ellipse(cr, 0, by + 2.5, self.body_rx * 0.74, self.body_ry * 0.9)
            paint(cr, k.belly)
        elif self.led:
            rounded_rect(cr, -9.5, by - 6, 19, 13, 3.5)
            paint(cr, k.belly, k.line, lw=1.4)
            beat = 0.55 + 0.45 * math.sin(p.t * 2.6)
            ellipse(cr, -4.5, by + 0.5, 2.3, 2.3)
            paint(cr, k.extra, None, alpha=0.45 + 0.55 * beat)
            for i in range(3):
                rounded_rect(cr, 0.5, by - 3.2 + i * 3.4, 6.5, 1.7, 0.8)
                paint(cr, k.line, None, alpha=0.55)
        else:
            ellipse(cr, 0, by + 3.0, self.body_rx * 0.62, self.body_ry * 0.74)
            paint(cr, k.belly)
            if self.spec.get("plates"):
                for i in range(3):
                    yy = by - 3.5 + i * 5.2
                    cr.new_path()
                    cr.move_to(-9, yy)
                    cr.curve_to(-4, yy + 2.2, 4, yy + 2.2, 9, yy)
                    stroke(cr, mix(k.belly, k.line, 0.35), 1.4)
        if d.pattern == "tabby":
            for side in (-1, 1):
                for i in range(2):
                    yy = by - 5 + i * 6.5
                    cr.new_path()
                    cr.move_to(side * (self.body_rx + 1), yy)
                    cr.line_to(side * (self.body_rx - 7), yy + 1.6)
                    stroke(cr, k.stripe, 2.6)
        elif d.pattern == "spots":
            for sx, sy, r in ((-13, -4, 3.2), (14, 3, 2.6)):
                ellipse(cr, sx, by + sy, r, r * 0.85)
                paint(cr, k.shade)
        elif d.pattern == "tuxedo":
            ellipse(cr, 0, by - 9, self.body_rx * 0.7, self.body_ry * 0.75)
            paint(cr, k.belly)
        cr.restore()
        self.body_path()
        paint(cr, None, k.line)

    def arm(self, side, angle, fwd, target=None):
        cr, k, p = self.cr, self.k, self.p
        sx, sy = side * (self.body_rx - 3.0), self.body_cy - 6.5 + p.lie * 3
        length = 11.0
        ex = sx + side * math.sin(angle) * length
        ey = sy + math.cos(angle) * length
        if fwd:
            tx, ty = side * 7.5, self.body_cy + 4.5
            ex += (tx - ex) * fwd
            ey += (ty - ey) * fwd
        if target is not None:
            ex, ey = target
        self.hands[side] = (ex, ey)
        if self.human:
            tube(cr, ((sx, sy), (ex, ey)), 7.0, k.limb, k.limb_line)
            _human.hand(self, side, sx, sy, ex, ey)
            return
        if self.spec.get("flippers"):
            cr.save()
            cr.translate(sx, sy)
            cr.rotate(-side * (angle + 0.1))
            blob(cr, 0, 7, 5.2, 9.5, 0.55, 0.6)
            cr.restore()
            paint(cr, k.fur, k.line)
            return
        tube(cr, ((sx, sy), (ex, ey)), 7.2, k.limb, k.limb_line)

    # -- head -----------------------------------------------------------

    def head_path(self):
        blob(self.cr, 0, 0, self.head_rx, self.head_ry, self.head_kt, self.head_kb)

    def head(self):
        cr, p, k, d, spec = self.cr, self.p, self.k, self.d, self.spec
        f = p.facing
        cr.save()
        cr.translate(self.head_cx, self.head_cy)
        if p.head_tilt:
            cr.rotate(p.head_tilt)
        ears = spec.get("ears", "none")
        if self.human:
            _human.hair_back(self, f)
            _human.ears(self, f)
        elif ears in ("cat", "fox", "bunny", "round", "horns", "antenna", "gills", "bumps"):
            self.ears(ears)
        if d.accessory == "headphones" or p.hat == "headphones":
            self.headphones(back=True)
        base, base_line = (k.skin, k.skin_line) if self.human else (k.fur, k.line)
        if self.flat:
            self.head_path()
            paint(cr, base, base_line)
        else:
            self.head_path()
            cr.save()
            cr.clip()
            src(cr, base)
            cr.paint()
            if self.human:
                _human.hair_cap(self, f)
                if spec.get("tattoo"):
                    _human.tattoo(self, f)
            else:
                self.head_markings(f)
            cr.restore()
            self.head_path()
            paint(cr, None, base_line)
        if ears == "flop":
            self.ears(ears)
        if self.human:
            _human.hair_front(self, f)
        if not self.flat:
            if spec.get("visor"):
                rounded_rect(cr, -21 + f * 2.5, -9.5, 42, 24, 9)
                paint(cr, rgb("#1F2433"), k.line, lw=1.8)
            self.face(f)
        self.head_accessory(f)
        if p.hat and p.hat != "headphones":
            self.hat(p.hat)
        if not self.flat:
            self.face_marks(f)
        cr.restore()

    def head_markings(self, f):
        """Drawn clipped to the head shape."""
        cr, k, d, spec = self.cr, self.k, self.d, self.spec
        ry, rx = self.head_ry, self.head_rx
        if spec.get("mask") or d.pattern == "tuxedo":
            cr.new_path()
            cr.move_to(-rx - 2, 4)
            cr.curve_to(-14 + f * 6, 2, -6 + f * 7, -6, f * 7, 3)
            cr.curve_to(6 + f * 7, -6, 14 + f * 6, 2, rx + 2, 4)
            cr.line_to(rx + 2, ry + 2)
            cr.line_to(-rx - 2, ry + 2)
            cr.close_path()
            paint(cr, k.belly)
        if spec.get("face_mask"):
            for side in (-1, 1):
                ellipse(cr, side * 10.5 + f * 4.5, 2.5, 12.5, 13)
                paint(cr, k.belly)
            ellipse(cr, f * 5, 13, 17, 12)
            paint(cr, k.belly)
        if spec.get("muzzle"):
            ellipse(cr, f * 7, 10.5, 11.5, 8.2)
            paint(cr, k.belly)
        if spec.get("eye_patches"):
            for side in (-1, 1):
                ellipse(cr, side * self.eye_dx + f * 5.5, self.eye_y + 0.5, 8.0, 9.6, side * 0.38)
                paint(cr, k.extra)
        if d.pattern == "patch":
            ellipse(cr, self.eye_dx + f * 5.5, self.eye_y, 9.5, 10.5, 0.3)
            paint(cr, k.shade)
        if d.pattern == "tabby":
            for x in (-6.5, 0.0, 6.5):
                cr.new_path()
                cr.move_to(x + f * 3, -ry - 1)
                cr.line_to(x * 0.85 + f * 3, -ry + (9.5 if x == 0 else 7.5))
                stroke(cr, k.stripe, 2.8)
            for side in (-1, 1):
                for yy in (3.0, 9.5):
                    cr.new_path()
                    cr.move_to(side * (rx + 1), yy)
                    cr.line_to(side * (rx - 6.5), yy + 1.2)
                    stroke(cr, k.stripe, 2.6)
        elif d.pattern == "spots":
            for sx, sy, r in ((-16, -17, 4.6), (-7, -22, 2.6), (19, -14, 3.4)):
                ellipse(cr, sx + f * 2, sy, r, r * 0.85)
                paint(cr, k.shade)

    def ears(self, kind):
        cr, p, k = self.cr, self.p, self.k
        f = p.facing
        droop = max(0.0, -p.ear)
        perk = max(0.0, p.ear)
        rx, ry = self.head_rx, self.head_ry
        if kind in ("cat", "fox"):
            tall = 40.0 if kind == "cat" else 46.0
            for side in (-1, 1):
                ox = -f * 1.5
                tip = (side * (23.5 + droop * 11) + ox, -tall + droop * 16 - perk * 3)
                outer = (side * 29.5 + ox, -9.0)
                inner = (side * 6.5 + ox, -22.5)
                def ear_path():
                    cr.new_path()
                    cr.move_to(*outer)
                    cr.curve_to(outer[0], outer[1] - 12, tip[0] + side * 3, tip[1] + 6, tip[0], tip[1])
                    cr.curve_to(tip[0] - side * 5, tip[1] + 5, inner[0] + side * 2, inner[1] - 8,
                                inner[0], inner[1])
                    cr.close_path()

                ear_path()
                if kind == "fox":
                    cr.save()
                    cr.clip()
                    src(cr, k.fur)
                    cr.paint()
                    ellipse(cr, tip[0], tip[1], 9, 12)
                    paint(cr, k.extra)
                    cr.restore()
                    ear_path()
                    paint(cr, None, k.line)
                else:
                    paint(cr, k.ear, k.line)
                cx = (outer[0] + inner[0] + tip[0]) / 3.0
                cy = (outer[1] + inner[1] + tip[1]) / 3.0
                cr.new_path()
                cr.move_to(cx + (outer[0] - cx) * 0.5, cy + (outer[1] - cy) * 0.35)
                cr.line_to(cx + (tip[0] - cx) * 0.5, cy + (tip[1] - cy) * 0.5)
                cr.line_to(cx + (inner[0] - cx) * 0.5, cy + (inner[1] - cy) * 0.35)
                cr.close_path()
                src(cr, k.inner)
                cr.set_line_width(2.0)
                cr.fill_preserve()
                cr.stroke()
        elif kind == "bunny":
            for side in (-1, 1):
                bend = 0.14 + droop * 1.15 + (0.34 if side > 0 else 0.0) * (1 - perk)
                cr.save()
                cr.translate(side * 11.5 - f * 1.5, -ry + 5)
                cr.rotate(side * bend)
                blob(cr, 0, -17, 6.8, 19.5, 0.6, 0.5)
                paint(cr, k.ear, k.line)
                blob(cr, 0, -17, 3.2, 14.0, 0.6, 0.5)
                paint(cr, k.inner)
                cr.restore()
        elif kind == "round":
            for side in (-1, 1):
                ellipse(cr, side * 22.5 - f * 1.5, -ry + 5.5 + droop * 2, 9.8, 9.8)
                paint(cr, k.ear, outline_of(k.ear))
                if not self.spec.get("dark_ears"):
                    ellipse(cr, side * 22.5 - f * 1.5, -ry + 6.5 + droop * 2, 5.0, 5.0)
                    paint(cr, k.inner)
        elif kind == "flop":
            ear = k.extra
            flap = perk * 0.5 - droop * 0.1 + math.sin(p.t * 7.0) * 0.06 * perk
            for side in (-1, 1):
                cr.save()
                cr.translate(side * (rx - 7.5) - f * 1.5, -ry + 9)
                cr.rotate(-side * (0.2 + flap))
                blob(cr, side * 6.5, 13, 8.2, 15.5, 0.55, 0.7)
                paint(cr, ear, outline_of(ear))
                cr.restore()
        elif kind == "horns":
            horn = k.belly
            for side in (-1, 1):
                cr.new_path()
                cr.move_to(side * 8.5 - f * 1.5, -ry + 3)
                cr.curve_to(side * 10, -ry - 8, side * 16, -ry - 14, side * 21 - f * 1.5, -ry - 15)
                cr.curve_to(side * 21, -ry - 8, side * 20, -ry - 2, side * 18.5 - f * 1.5, -ry + 6)
                cr.close_path()
                paint(cr, horn, outline_of(mix(horn, k.fur, 0.4)))
            for side in (-1, 1):       # cheek fins
                cr.new_path()
                cr.move_to(side * (rx - 3), -3)
                cr.line_to(side * (rx + 8), -1 + droop * 3)
                cr.line_to(side * (rx - 2), 7)
                cr.close_path()
                paint(cr, k.extra, outline_of(k.extra))
        elif kind == "antenna":
            cr.new_path()
            cr.move_to(-f * 1.5, -ry + 1)
            cr.line_to(-f * 1.5 + p.tail * 1.5, -ry - 11)
            stroke(cr, k.line, 2.4)
            pulse = 0.6 + 0.4 * math.sin(p.t * 3.9)
            ellipse(cr, -f * 1.5 + p.tail * 1.5, -ry - 13.5, 4.0, 4.0)
            paint(cr, mix(k.extra, WHITE, 0.25 * pulse), outline_of(k.extra), lw=1.6)
            for side in (-1, 1):
                rounded_rect(cr, side * (rx - 1) - 3.2, -6, 6.4, 13, 2.4)
                paint(cr, darken(k.fur, 0.18), k.line, lw=1.8)
        elif kind == "gills":
            wob = math.sin(p.t * 2.6) * 0.1
            for side in (-1, 1):
                for i, ang in enumerate((-0.75, -0.15, 0.45)):
                    a = ang + wob * (1 if i % 2 else -1) + droop * 0.3
                    x0 = side * (rx - 4)
                    y0 = -9 + i * 7.5
                    x1 = x0 + side * math.cos(a) * 14.5
                    y1 = y0 + math.sin(a) * 14.5
                    tube(cr, ((x0, y0), (x1, y1)), 4.6, k.extra, outline_of(k.extra), lw=1.7)
        elif kind == "bumps":
            for side in (-1, 1):
                ellipse(cr, side * self.eye_dx + f * 3.5, -ry + 6.5, 10.5, 10.5)
                paint(cr, k.fur, k.line)

    # -- face -----------------------------------------------------------

    def face(self, f):
        cr, p, k, spec = self.cr, self.p, self.k, self.spec
        ey = self.eye_y
        if self.human:
            if spec.get("shades"):
                _human.shades(self, f)
            else:
                for side in (-1, 1):
                    near = max(0.0, side * f)
                    scale = self.eye_scale * (1.45 if (p.prop == "magnifier" and side == 1) else 1.0)
                    self.eye(side * self.eye_dx + f * 5.5, ey, side, scale, 1 - 0.2 * near)
            self.brows(f, ey)
            if p.blush > 0.02:
                for side in (-1, 1):
                    ellipse(cr, side * (self.eye_dx + 8.0) + f * 4, ey + 8.0, 4.6, 2.9)
                    paint(cr, k.cheek, None, alpha=min(0.8, 0.12 + 0.45 * p.blush))
            nx = f * 8.0
            _human.nose(self, nx, ey + 6.2)
            self.mouth(nx, ey + 10.8)
            _human.facial_hair(self, nx, ey + 10.8)
            return
        for side in (-1, 1):
            near = max(0.0, side * f)
            scale = self.eye_scale * (1.45 if (p.prop == "magnifier" and side == 1) else 1.0)
            self.eye(side * self.eye_dx + f * 5.5, ey, side, scale, 1 - 0.2 * near)
        if p.brow:
            self.brows(f, ey)
        if not self.led and p.blush > 0.02:
            for side in (-1, 1):
                ellipse(cr, side * (self.eye_dx + 8.5) + f * 4, ey + 8.5, 5.0, 3.1)
                paint(cr, k.cheek, None, alpha=min(0.95, 0.2 + 0.55 * p.blush))
        nose = spec.get("nose", "none")
        nx, ny = f * 8.0, ey + 5.6
        if nose == "tri":
            cr.new_path()
            cr.move_to(nx - 2.5, ny - 1.2)
            cr.curve_to(nx - 1, ny - 2.1, nx + 1, ny - 2.1, nx + 2.5, ny - 1.2)
            cr.curve_to(nx + 1.6, ny + 0.8, nx + 0.6, ny + 1.6, nx, ny + 1.7)
            cr.curve_to(nx - 0.6, ny + 1.6, nx - 1.6, ny + 0.8, nx - 2.5, ny - 1.2)
            cr.close_path()
            paint(cr, k.nose)
        elif nose == "oval":
            ellipse(cr, nx, ny + 0.2, 3.6, 2.5)
            paint(cr, k.nose)
            ellipse(cr, nx - 1.0, ny - 0.6, 1.0, 0.6)
            paint(cr, WHITE, None, alpha=0.5)
        elif nose == "dots":
            for side in (-1, 1):
                ellipse(cr, nx + side * 2.6, ny - 0.5, 0.95, 0.95)
                paint(cr, k.line)
        if spec.get("whiskers"):
            for side in (-1, 1):
                for i, dy in enumerate((-1.2, 2.6)):
                    x0 = side * (self.eye_dx + 9.5) + f * 4
                    cr.new_path()
                    cr.move_to(x0, ey + 6.5 + dy)
                    cr.line_to(x0 + side * 9.5, ey + 5.2 + dy * 2.1)
                    stroke(cr, k.line, 1.1, 0.75)
        if nose == "beak":
            self.beak(nx, ny + 0.5)
        else:
            self.mouth(nx, ey + 9.2)
        if spec.get("fang") and p.mouth in ("smile", "cat", "flat", "frown"):
            cr.new_path()
            cr.move_to(nx + 2.2, ey + 10.2)
            cr.line_to(nx + 3.4, ey + 13.2)
            cr.line_to(nx + 4.6, ey + 10.0)
            cr.close_path()
            paint(cr, WHITE, k.line, lw=1.0)

    def eye(self, cx, cy, side, scale, narrow):
        cr, p, k = self.cr, self.p, self.k
        kind = p.eye
        col = k.extra if self.led else k.eye
        rx, ry = 4.4 * scale * narrow, 5.9 * scale
        lx = p.look[0] * 1.5
        ly = p.look[1] * 1.3
        lid_line = k.extra if self.led else k.line
        if kind in ("open", "sleepy", "angry", "sad"):
            openness = max(0.0, min(1.0, p.eye_open))
            if kind == "sleepy":
                openness = min(openness, 0.55)
            if openness < 0.2:
                cr.new_path()
                cr.move_to(cx - rx * 1.05, cy + 1.0)
                cr.curve_to(cx - rx * 0.4, cy + 2.6, cx + rx * 0.4, cy + 2.6, cx + rx * 1.05, cy + 1.0)
                stroke(cr, col, 2.2)
                return
            ex, eyy = cx + lx, cy + ly + (1 - openness) * ry * 0.45
            ellipse(cr, ex, eyy, rx, ry * openness)
            paint(cr, col)
            if not self.led:
                ellipse(cr, ex - rx * 0.32, eyy - ry * 0.36 * openness, 1.6 * scale, 1.6 * scale * min(1, openness + 0.2))
                paint(cr, WHITE)
                ellipse(cr, ex + rx * 0.36, eyy + ry * 0.34 * openness, 0.8 * scale, 0.8 * scale)
                paint(cr, WHITE, None, alpha=0.85)
            if kind == "sleepy":
                cr.new_path()
                cr.move_to(cx - rx * 1.25, eyy - ry * openness * 0.55)
                cr.line_to(cx + rx * 1.25, eyy - ry * openness * 0.55)
                stroke(cr, lid_line, 1.8)
            return
        if kind == "happy":
            cr.new_path()
            cr.move_to(cx - rx * 1.1, cy + 2.2)
            cr.curve_to(cx - rx * 0.6, cy - ry * 0.85, cx + rx * 0.6, cy - ry * 0.85, cx + rx * 1.1, cy + 2.2)
            stroke(cr, col, 2.5)
        elif kind == "closed":
            cr.new_path()
            cr.move_to(cx - rx * 1.05, cy + 0.2)
            cr.curve_to(cx - rx * 0.5, cy + ry * 0.55, cx + rx * 0.5, cy + ry * 0.55, cx + rx * 1.05, cy + 0.2)
            stroke(cr, col, 2.3)
        elif kind == "wide":
            r = ry * 1.02
            ellipse(cr, cx, cy, r * narrow, r)
            if self.led:
                stroke(cr, col, 2.0)
            else:
                paint(cr, WHITE, k.line, lw=1.6)
            ellipse(cr, cx + lx, cy + ly, r * 0.36, r * 0.36)
            paint(cr, col)
        elif kind == "sparkle":
            ellipse(cr, cx, cy, rx * 1.18, ry * 1.1)
            paint(cr, col)
            if not self.led:
                star_path(cr, cx - rx * 0.2, cy - ry * 0.25, 3.3 * scale, 1.1 * scale, 4,
                          math.sin(p.t * 5.0) * 0.3)
                paint(cr, WHITE)
                ellipse(cr, cx + rx * 0.42, cy + ry * 0.42, 1.0 * scale, 1.0 * scale)
                paint(cr, WHITE)
        elif kind == "heart":
            beat = 1 + 0.12 * math.sin(p.t * 8.0)
            heart_path(cr, cx, cy, 4.3 * scale * beat)
            paint(cr, rgb("#FF5C8A"), outline_of(rgb("#FF5C8A")), lw=1.2)
        elif kind == "spiral":
            cr.new_path()
            turns, steps = 2.2, 26
            spin = p.t * 6.0 * side
            for i in range(steps + 1):
                a = spin + turns * TAU * i / steps
                r = ry * 0.98 * i / steps
                x, y = cx + r * math.cos(a) * narrow, cy + r * math.sin(a)
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            stroke(cr, col, 1.7)
        elif kind == "x":
            for dx in (-1, 1):
                cr.new_path()
                cr.move_to(cx - rx * 0.95 * dx, cy - ry * 0.6)
                cr.line_to(cx + rx * 0.95 * dx, cy + ry * 0.6)
                stroke(cr, col, 2.3)
        elif kind == "squeeze":
            cr.new_path()
            cr.move_to(cx - side * rx * 0.95, cy - ry * 0.6)
            cr.line_to(cx + side * rx * 0.75, cy)
            cr.line_to(cx - side * rx * 0.95, cy + ry * 0.6)
            stroke(cr, col, 2.4)

    def brows(self, f, ey):
        cr, p, k = self.cr, self.p, self.k
        col = k.extra if self.led else k.line
        width = 2.0
        if self.human:
            col = k.hair if luminance(k.hair) < 0.6 else k.hair_line
            width = self.spec.get("brow_w", 2.4)
        for side in (-1, 1):
            cx = side * self.eye_dx + f * 5.5
            y = ey - 5.9 * self.eye_scale - 3.0
            inner, outer = (cx - side * 4.6, y), (cx + side * 4.6, y)
            if not p.brow:
                inner, outer = (inner[0], y + 0.3), (outer[0], y + 0.9)
            if p.brow == "angry":
                inner = (inner[0], y + 2.6)
                outer = (outer[0], y - 1.4)
            elif p.brow == "sad":
                inner = (inner[0], y - 2.2)
                outer = (outer[0], y + 1.6)
            elif p.brow == "raised":
                inner = (inner[0], y - 2.2)
                outer = (outer[0], y - 2.6)
            cr.new_path()
            cr.move_to(*inner)
            cr.curve_to(inner[0] + side * 2.6, min(inner[1], outer[1]) - (1.2 if not p.brow else 0.0),
                        outer[0] - side * 2.6, min(inner[1], outer[1]) - (1.2 if not p.brow else 0.0),
                        outer[0], outer[1])
            stroke(cr, col, width)

    def mouth(self, mx, my):
        cr, p, k = self.cr, self.p, self.k
        kind = p.mouth
        if kind == "smile" and self.spec.get("mouth") == "cat":
            kind = "cat"
        w = self.spec.get("wide_mouth", 1.0)
        col = k.extra if self.led else k.line
        op = max(0.0, min(1.0, p.mouth_open))
        if kind == "none":
            return
        if kind == "smile":
            cr.new_path()
            cr.move_to(mx - 3.3 * w, my - 0.7)
            cr.curve_to(mx - 1.6 * w, my + 2.5, mx + 1.6 * w, my + 2.5, mx + 3.3 * w, my - 0.7)
            stroke(cr, col, 1.9)
        elif kind == "cat":
            for side in (-1, 1):
                cr.new_path()
                cr.move_to(mx, my - 0.6)
                cr.curve_to(mx + side * 0.6, my + 2.6, mx + side * 4.2, my + 2.6, mx + side * 4.8, my - 0.5)
                stroke(cr, col, 1.8)
            cr.new_path()
            cr.move_to(mx, my - 2.4)
            cr.line_to(mx, my - 0.6)
            stroke(cr, col, 1.5)
        elif kind in ("grin", "tongue"):
            h = 5.8 * (0.45 + 0.55 * op)

            def grin_path():
                cr.new_path()
                cr.move_to(mx - 4.4 * w, my - 1.1)
                cr.line_to(mx + 4.4 * w, my - 1.1)
                cr.curve_to(mx + 4.0 * w, my + h, mx - 4.0 * w, my + h, mx - 4.4 * w, my - 1.1)
                cr.close_path()

            grin_path()
            if self.led:
                paint(cr, col)
            else:
                cr.save()
                cr.clip()
                src(cr, MOUTH_DARK)
                cr.paint()
                ellipse(cr, mx, my + h - 0.6, 3.0 * w, 2.1)
                paint(cr, TONGUE)
                cr.restore()
                grin_path()
                paint(cr, None, k.line, lw=1.6)
            if kind == "tongue" and not self.led:
                rounded_rect(cr, mx - 0.4, my + h * 0.45, 4.2, 5.4, 2.0)
                paint(cr, TONGUE, outline_of(TONGUE), lw=1.2)
        elif kind == "o":
            ellipse(cr, mx, my + 0.8, 2.0, 2.5 * (0.55 + 0.45 * op))
            paint(cr, col if self.led else MOUTH_DARK, None if self.led else k.line, lw=1.3)
        elif kind == "yawn":
            yh = 5.0 * (0.35 + 0.65 * op)
            ellipse(cr, mx, my + 1.8, 3.8, yh)
            if self.led:
                paint(cr, col)
            else:
                cr.save()
                cr.clip()
                src(cr, MOUTH_DARK)
                cr.paint()
                ellipse(cr, mx, my + 1.8 + yh - 1.2, 2.8, 2.2)
                paint(cr, TONGUE)
                cr.restore()
                ellipse(cr, mx, my + 1.8, 3.8, yh)
                paint(cr, None, k.line, lw=1.5)
        elif kind == "flat":
            cr.new_path()
            cr.move_to(mx - 3.0 * w, my + 0.6)
            cr.line_to(mx + 3.0 * w, my + 0.6)
            stroke(cr, col, 1.9)
        elif kind == "frown":
            cr.new_path()
            cr.move_to(mx - 3.2 * w, my + 2.0)
            cr.curve_to(mx - 1.5 * w, my - 0.9, mx + 1.5 * w, my - 0.9, mx + 3.2 * w, my + 2.0)
            stroke(cr, col, 1.9)
        elif kind == "wavy":
            cr.new_path()
            cr.move_to(mx - 4.4, my + 0.8)
            cr.curve_to(mx - 3.2, my - 1.4, mx - 1.6, my - 1.4, mx - 0.4, my + 0.8)
            cr.curve_to(mx + 0.8, my + 2.8, mx + 2.6, my + 2.8, mx + 4.2, my + 0.4)
            stroke(cr, col, 1.8)
        elif kind == "teeth":
            rounded_rect(cr, mx - 4.6, my - 1.4, 9.2, 4.4, 1.6)
            paint(cr, col if self.led else WHITE, None if self.led else k.line, lw=1.4)
            if not self.led:
                for dx in (-1.5, 1.5):
                    cr.new_path()
                    cr.move_to(mx + dx, my - 1.2)
                    cr.line_to(mx + dx, my + 2.8)
                    stroke(cr, k.line, 0.9)

    def beak(self, bx, by):
        cr, p, k = self.cr, self.p, self.k
        beak = k.extra
        line = outline_of(beak)
        opened = p.mouth in ("grin", "tongue", "o", "yawn", "teeth")
        gap = (1.2 + 3.2 * p.mouth_open) if opened else 0.0
        if opened:
            cr.new_path()
            cr.move_to(bx - 4.4, by + 0.6)
            cr.line_to(bx + 4.4, by + 0.6)
            cr.line_to(bx, by + 3.6 + gap)
            cr.close_path()
            paint(cr, MOUTH_DARK, line, lw=1.3)
        cr.new_path()
        cr.move_to(bx - 5.4, by - 1.6)
        cr.curve_to(bx - 2.5, by - 3.2, bx + 2.5, by - 3.2, bx + 5.4, by - 1.6)
        cr.curve_to(bx + 3.2, by + 1.6, bx + 1.2, by + 3.4, bx, by + 3.6)
        cr.curve_to(bx - 1.2, by + 3.4, bx - 3.2, by + 1.6, bx - 5.4, by - 1.6)
        cr.close_path()
        paint(cr, beak, line, lw=1.5)

    def face_marks(self, f):
        cr, p, k = self.cr, self.p, self.k
        marks = p.marks
        if not marks:
            return
        rx, ry = self.head_rx, self.head_ry
        ey = self.eye_y
        if "sweat" in marks:
            side = -1 if f >= 0 else 1
            slide = (p.t * 0.9) % 1.0
            drop_path(cr, side * (rx - 6), -ry + 9 + slide * 7, 3.0)
            paint(cr, TEAR, TEAR_D, lw=1.2, alpha=1 - slide * 0.5)
        if "tear" in marks:
            for side in (-1, 1):
                fall = ((p.t * 0.8 + (0.4 if side > 0 else 0)) % 1.0)
                drop_path(cr, side * self.eye_dx + f * 5.5 + side * 1.5, ey + 8 + fall * 9, 2.1)
                paint(cr, TEAR, TEAR_D, lw=1.0, alpha=1 - fall * 0.7)
        if "anger" in marks:
            ax, ay = (rx - 9) * (1 if f <= 0 else -1), -ry + 8
            red = rgb("#F43F5E")
            pulse = 1 + 0.12 * math.sin(p.t * 10)
            for qx, qy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                cr.new_path()
                cr.move_to(ax + qx * 1.2 * pulse, ay + qy * 4.4 * pulse)
                cr.curve_to(ax + qx * 1.2 * pulse, ay + qy * 1.6, ax + qx * 1.6, ay + qy * 1.2 * pulse,
                            ax + qx * 4.4 * pulse, ay + qy * 1.2 * pulse)
                stroke(cr, red, 1.8)
        if "gloom" in marks:
            for i, x in enumerate((-9, -5, -1, 3)):
                cr.new_path()
                cr.move_to(x + 12, -ry + 4)
                cr.line_to(x + 12, -ry + 10 + (i % 2) * 3)
                stroke(cr, INK, 1.2, 0.45)
        if "bandage" in marks:
            cr.save()
            cr.translate(-10, -ry + 9)
            cr.rotate(-0.5)
            rounded_rect(cr, -7, -2.6, 14, 5.2, 2.2)
            paint(cr, rgb("#FFE8C7"), rgb("#C79A63"), lw=1.2)
            cr.rotate(1.2)
            rounded_rect(cr, -7, -2.6, 14, 5.2, 2.2)
            paint(cr, rgb("#FFE8C7"), rgb("#C79A63"), lw=1.2)
            cr.restore()
        if "thermo" in marks:
            mx, my = f * 8.0, ey + 9.6
            tube(cr, ((mx + 1, my), (mx + 12, my - 5)), 2.2, WHITE, k.line, lw=1.0)
            ellipse(cr, mx + 13, my - 5.5, 2.3, 2.3)
            paint(cr, rgb("#F43F5E"), k.line, lw=1.0)

    # -- accessories ----------------------------------------------------

    def neck_accessory(self):
        cr, k, d = self.cr, self.k, self.d
        y = self.head_cy + self.head_ry - 2.5
        x = self.head_cx
        if d.accessory == "scarf":
            cr.new_path()
            cr.move_to(x - 17, y - 2)
            cr.curve_to(x - 9, y + 5, x + 9, y + 5, x + 17, y - 2)
            cr.line_to(x + 17, y + 3)
            cr.curve_to(x + 9, y + 10, x - 9, y + 10, x - 17, y + 3)
            cr.close_path()
            paint(cr, k.accent, k.accent_line, lw=1.8)
            rounded_rect(cr, x + 7, y + 5, 6.5, 12, 2.5)
            paint(cr, k.accent, k.accent_line, lw=1.8)
        elif d.accessory == "bandana":
            cr.new_path()
            cr.move_to(x - 16, y - 1)
            cr.curve_to(x - 8, y + 4, x + 8, y + 4, x + 16, y - 1)
            cr.line_to(x, y + 15)
            cr.close_path()
            paint(cr, k.accent, k.accent_line, lw=1.8)
            for dx, dy in ((-5, 4.5), (5, 4.5), (0, 9)):
                ellipse(cr, x + dx, y + dy, 1.0, 1.0)
                paint(cr, WHITE, None, alpha=0.85)

    def bowtie(self):
        """Drawn in the head frame, just under the chin, so it follows the head."""
        cr, k = self.cr, self.k
        y = self.head_ry + 1.5
        for side in (-1, 1):
            cr.new_path()
            cr.move_to(0, y)
            cr.line_to(side * 9, y - 5)
            cr.line_to(side * 9, y + 5)
            cr.close_path()
            paint(cr, k.accent, k.accent_line, lw=1.6)
        ellipse(cr, 0, y, 2.6, 2.9)
        paint(cr, lighten(k.accent, 0.2), k.accent_line, lw=1.4)

    def headphones(self, back=False):
        cr, k = self.cr, self.k
        rx, ry = self.head_rx, self.head_ry
        if back:
            cr.new_path()
            cr.arc(0, -2, rx + 1.5, math.pi * 1.08, math.pi * 1.92)
            stroke(cr, k.accent_line, 6.4)
            cr.new_path()
            cr.arc(0, -2, rx + 1.5, math.pi * 1.08, math.pi * 1.92)
            stroke(cr, k.accent, 3.4)
            return
        for side in (-1, 1):
            rounded_rect(cr, side * (rx + 0.5) - 4.5, -8, 9, 17, 4)
            paint(cr, k.accent, k.accent_line, lw=1.8)
            rounded_rect(cr, side * (rx + 0.5) - 1.5 - side * 2.5, -5, 3, 11, 1.5)
            paint(cr, darken(k.accent, 0.25))

    def head_accessory(self, f):
        cr, k, d, p = self.cr, self.k, self.d, self.p
        acc = d.accessory
        rx, ry = self.head_rx, self.head_ry
        if acc == "bowtie":
            self.bowtie()
        if acc == "glasses" or p.glasses:
            frame = rgb("#3A3342")
            for side in (-1, 1):
                ellipse(cr, side * self.eye_dx + f * 5.5, self.eye_y, 7.4, 7.4)
                src(cr, WHITE, 0.16)
                cr.fill_preserve()
                stroke(cr, frame, 1.9)
            cr.new_path()
            cr.move_to(-self.eye_dx + 7.4 + f * 5.5, self.eye_y - 1)
            cr.curve_to(-2 + f * 5.5, self.eye_y - 3, 2 + f * 5.5, self.eye_y - 3,
                        self.eye_dx - 7.4 + f * 5.5, self.eye_y - 1)
            stroke(cr, frame, 1.9)
        if acc == "headphones" or p.hat == "headphones":
            self.headphones()
        elif acc == "flower":
            cx, cy = (rx - 8.5), -ry + 7
            for i in range(5):
                a = i * TAU / 5 + 0.3
                ellipse(cr, cx + math.cos(a) * 4.2, cy + math.sin(a) * 4.2, 3.4, 3.4)
                paint(cr, k.accent, k.accent_line, lw=1.2)
            ellipse(cr, cx, cy, 2.6, 2.6)
            paint(cr, GOLD, outline_of(GOLD), lw=1.1)
        if p.hat and p.hat != "headphones":
            return                      # contextual hats replace worn headwear
        if acc == "crown":
            y = -ry + 2.5
            cr.new_path()
            cr.move_to(-12, y)
            cr.line_to(-13.5, y - 12)
            cr.line_to(-6.5, y - 6.5)
            cr.line_to(0, y - 14.5)
            cr.line_to(6.5, y - 6.5)
            cr.line_to(13.5, y - 12)
            cr.line_to(12, y)
            cr.close_path()
            paint(cr, GOLD, outline_of(GOLD), lw=1.8)
            for gx, col in ((-7, "#FB7185"), (0, "#38BDF8"), (7, "#4ADE80")):
                ellipse(cr, gx, y - 3.3, 1.7, 1.7)
                paint(cr, rgb(col))
        elif acc == "beanie":
            y = -ry + 9
            cr.new_path()
            cr.move_to(-rx + 3.5, y)
            cr.curve_to(-rx + 4, y - 26, rx - 4, y - 26, rx - 3.5, y)
            cr.close_path()
            paint(cr, k.accent, k.accent_line)
            rounded_rect(cr, -rx + 1.5, y - 4, 2 * rx - 3, 7.5, 3.5)
            paint(cr, lighten(k.accent, 0.28), k.accent_line, lw=1.8)
            ellipse(cr, 0, y - 21.5, 4.6, 4.6)
            paint(cr, lighten(k.accent, 0.45), k.accent_line, lw=1.6)
        elif acc == "cap":
            y = -ry + 8
            side = 1 if f >= 0 else -1
            cr.new_path()
            cr.move_to(-rx + 5, y)
            cr.curve_to(-rx + 6, y - 22, rx - 6, y - 22, rx - 5, y)
            cr.close_path()
            paint(cr, k.accent, k.accent_line)
            cr.new_path()
            cr.move_to(side * (rx - 14), y - 1.5)
            cr.curve_to(side * (rx - 2), y - 4, side * (rx + 10), y - 2, side * (rx + 12), y + 2.5)
            cr.curve_to(side * (rx + 2), y + 3.5, side * (rx - 6), y + 3, side * (rx - 14), y + 2)
            cr.close_path()
            paint(cr, darken(k.accent, 0.18), k.accent_line, lw=1.8)
        elif acc == "wizard":
            y = -ry + 6
            cr.new_path()
            cr.move_to(-17, y)
            cr.curve_to(-9, y - 22, -2, y - 30, 12, y - 38)
            cr.curve_to(9, y - 24, 14, y - 12, 17, y)
            cr.close_path()
            paint(cr, k.accent, k.accent_line)
            cr.new_path()
            cr.move_to(-25, y + 1)
            cr.curve_to(-12, y - 5, 12, y - 5, 25, y + 1)
            cr.curve_to(12, y + 5, -12, y + 5, -25, y + 1)
            cr.close_path()
            paint(cr, darken(k.accent, 0.15), k.accent_line, lw=1.8)
            star_path(cr, 1, y - 15, 4.2, 1.7, 5, 0.2)
            paint(cr, GOLD)

    def hat(self, kind):
        cr, k, p = self.cr, self.k, self.p
        ry = self.head_ry
        if kind == "party":
            cr.save()
            cr.translate(7, -ry + 4)
            cr.rotate(0.28)
            def cone():
                cr.new_path()
                cr.move_to(-10.5, 0)
                cr.line_to(0, -25)
                cr.line_to(10.5, 0)
                cr.close_path()

            cone()
            cr.save()
            cr.clip()
            src(cr, rgb("#8B5CF6"))
            cr.paint()
            for i in range(5):
                cr.new_path()
                cr.move_to(-14, -3 - i * 6.0)
                cr.line_to(14, -9 - i * 6.0)
                stroke(cr, rgb("#FCD34D"), 2.4)
            cr.restore()
            cone()
            paint(cr, None, outline_of(rgb("#8B5CF6")), lw=1.8)
            ellipse(cr, 0, -26, 3.6, 3.6)
            paint(cr, rgb("#FB7185"), outline_of(rgb("#FB7185")), lw=1.4)
            cr.restore()
        elif kind == "hardhat":
            y = -ry + 8
            hat = rgb("#FCD34D")
            cr.new_path()
            cr.move_to(-20, y)
            cr.curve_to(-20, y - 22, 20, y - 22, 20, y)
            cr.close_path()
            paint(cr, hat, outline_of(hat))
            rounded_rect(cr, -25, y - 2.5, 50, 6, 3)
            paint(cr, hat, outline_of(hat), lw=1.8)
            rounded_rect(cr, -3, y - 17, 6, 14, 2.5)
            paint(cr, lighten(hat, 0.35))
        elif kind == "nightcap":
            y = -ry + 8
            cap = rgb("#7C8CF8")
            sway = math.sin(p.t * 1.3) * 2.0
            cr.new_path()
            cr.move_to(-19, y)
            cr.curve_to(-16, y - 20, 4, y - 26, 20 + sway, y - 14)
            cr.curve_to(27 + sway, y - 9, 29 + sway, y - 1, 26 + sway, y + 6)
            cr.curve_to(22 + sway, y - 3, 20, y - 6, 19, y)
            cr.close_path()
            paint(cr, cap, outline_of(cap))
            rounded_rect(cr, -22, y - 3.5, 44, 7, 3.5)
            paint(cr, WHITE, outline_of(cap), lw=1.8)
            ellipse(cr, 26 + sway, y + 8.5, 4.2, 4.2)
            paint(cr, WHITE, outline_of(cap), lw=1.5)

    # -- props ----------------------------------------------------------

    def held_props(self):
        """Props carried in front of the body (drawn over body and head)."""
        cr, p, k = self.cr, self.p, self.k
        prop = p.prop
        by = self.body_cy
        if prop == "laptop":
            lid_top = by - 7.5
            rounded_rect(cr, -17.5, lid_top, 35, 21.5, 3.2)
            paint(cr, SILVER, rgb("#6E7686"), lw=1.9)
            star_path(cr, 0, lid_top + 10.5, 4.2, 1.6, 4, p.prop_t * 0.6)
            paint(cr, k.accent)
            rounded_rect(cr, -20.5, by + 13.2, 41, 4.4, 2.2)
            paint(cr, SILVER_D, rgb("#6E7686"), lw=1.7)
            beat = int(p.prop_t * 9.0)
            for side in (-1, 1):
                if (beat + (side > 0)) % 2:
                    continue
                for i in range(2):
                    a = -TAU / 4 + side * (0.35 + i * 0.45)
                    cr.new_path()
                    cr.move_to(side * 15 + math.cos(a) * 3, lid_top - 2 + math.sin(a) * 3)
                    cr.line_to(side * 15 + math.cos(a) * 6.5, lid_top - 2 + math.sin(a) * 6.5)
                    stroke(cr, k.line, 1.4, 0.75)
        elif prop == "book":
            top = by - 8.5
            for side in (-1, 1):
                cr.new_path()
                cr.move_to(0, top + 3)
                cr.line_to(side * 18.5, top)
                cr.line_to(side * 18.5, top + 16.5)
                cr.line_to(0, top + 19.5)
                cr.close_path()
                paint(cr, k.accent, k.accent_line, lw=1.9)
                cr.new_path()
                cr.move_to(side * 1.2, top + 1.6)
                cr.line_to(side * 17, top - 1.6)
                stroke(cr, PAPER, 2.2)
            cr.new_path()
            cr.move_to(0, top + 3)
            cr.line_to(0, top + 19.5)
            stroke(cr, k.accent_line, 1.9)
            for side in (-1, 1):
                ellipse(cr, side * 17.5, top + 9, 4.0, 4.6)
                paint(cr, k.limb, k.limb_line, lw=1.8)
        elif prop == "clipboard":
            x0, y0 = -11.5, by - 9.5
            rounded_rect(cr, x0, y0, 23, 26, 3)
            paint(cr, rgb("#C89B6D"), rgb("#7A5A3C"), lw=1.9)
            rounded_rect(cr, x0 + 2.6, y0 + 3.6, 17.8, 20, 1.6)
            paint(cr, PAPER)
            rounded_rect(cr, x0 + 7.5, y0 - 2, 8, 4.6, 1.6)
            paint(cr, SILVER_D, rgb("#6E7686"), lw=1.3)
            done = int(p.prop_t * 0.9) % 4
            for i in range(3):
                yy = y0 + 8.5 + i * 5.6
                if i < done:
                    cr.new_path()
                    cr.move_to(x0 + 4.6, yy)
                    cr.line_to(x0 + 6.2, yy + 1.6)
                    cr.line_to(x0 + 8.8, yy - 1.8)
                    stroke(cr, rgb("#16A34A"), 1.5)
                else:
                    rounded_rect(cr, x0 + 4.6, yy - 1.5, 3.2, 3.2, 0.8)
                    stroke(cr, rgb("#8F879B"), 1.0)
                cr.new_path()
                cr.move_to(x0 + 10.6, yy)
                cr.line_to(x0 + 18.4, yy)
                stroke(cr, rgb("#B5AEC0"), 1.4)
        elif prop == "mug":
            mx, my = 19.5, by + 1
            rounded_rect(cr, mx - 5.5, my - 5.5, 11, 11.5, 2.4)
            paint(cr, WHITE, k.line, lw=1.7)
            cr.new_path()
            cr.arc(mx + 5.6, my + 0.2, 3.3, -TAU / 4, TAU / 4)
            stroke(cr, k.line, 1.7)
            rounded_rect(cr, mx - 5.5, my - 1.2, 11, 3, 0.5)
            paint(cr, k.accent)
            for i in range(2):
                ph = (p.prop_t * 0.7 + i * 0.5) % 1.0
                cr.new_path()
                cr.move_to(mx - 2 + i * 4, my - 7 - ph * 6)
                cr.curve_to(mx - 4 + i * 4, my - 9.5 - ph * 6, mx + i * 4, my - 11 - ph * 6,
                            mx - 2 + i * 4, my - 13.5 - ph * 6)
                stroke(cr, WHITE, 1.3, 0.8 * (1 - ph))
        elif prop == "flag":
            sx = 21.0
            cr.new_path()
            cr.move_to(sx, by + 4)
            cr.line_to(sx, by - 34)
            stroke(cr, rgb("#7A5A3C"), 2.2)
            wave = math.sin(p.prop_t * 5.0) * 1.6
            cr.new_path()
            cr.move_to(sx, by - 34)
            cr.curve_to(sx + 7, by - 37 + wave, sx + 12, by - 31 - wave, sx + 19, by - 33 + wave)
            cr.line_to(sx + 19, by - 21 + wave)
            cr.curve_to(sx + 12, by - 19 - wave, sx + 7, by - 25 + wave, sx, by - 22)
            cr.close_path()
            green = rgb("#4ADE80")
            paint(cr, green, outline_of(green), lw=1.7)
            cr.new_path()
            cr.move_to(sx + 5.5, by - 28)
            cr.line_to(sx + 8.5, by - 25)
            cr.line_to(sx + 13.5, by - 31)
            stroke(cr, WHITE, 2.0)
        elif prop == "magnifier":
            cr.save()
            cr.translate(self.head_cx, self.head_cy)
            if p.head_tilt:
                cr.rotate(p.head_tilt)
            lx, ly = self.eye_dx + p.facing * 5.5, self.eye_y
            metal = rgb("#5B5568")
            tube(cr, ((lx + 8, ly + 8.5), (lx + 15.5, ly + 18)), 3.4, rgb("#C89B6D"), rgb("#7A5A3C"), lw=1.3)
            ellipse(cr, lx, ly, 11.2, 11.2)
            src(cr, rgb("#BDE7FF"), 0.22)
            cr.fill_preserve()
            stroke(cr, metal, 3.0)
            cr.new_path()
            cr.arc(lx, ly, 8.2, math.pi * 1.1, math.pi * 1.45)
            stroke(cr, WHITE, 1.6, 0.85)
            cr.restore()
        elif prop == "mirror":
            _human.mirror(self)
        elif prop == "sign":
            side = p.prop_side
            sx = side * 22.0
            bob = math.sin(p.prop_t * 6.0) * 1.8
            top = self.head_cy - self.head_ry - 21 + bob
            cr.new_path()
            cr.move_to(sx, by - 2)
            cr.line_to(sx, top + 14)
            stroke(cr, rgb("#7A5A3C"), 2.6)
            rounded_rect(cr, sx - 13, top, 26, 19, 4.5)
            paint(cr, rgb("#FFFAF0"), rgb("#7A5A3C"), lw=2.0)
            cr.select_font_face("Adwaita Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(16)
            ext = cr.text_extents(p.prop_text)
            cr.move_to(sx - ext.width / 2 - ext.x_bearing, top + 9.5 - ext.height / 2 - ext.y_bearing)
            src(cr, rgb("#F97316"))
            cr.show_text(p.prop_text)
            cr.new_path()

    def external_props(self):
        """Things that stand next to the pet (not affected by squash/lean)."""
        cr, p = self.cr, self.p
        prop = p.prop
        side = p.prop_side
        if prop == "chalkboard":
            _human.chalkboard(self, side)
        elif prop == "coil":
            _human.coil(self, side)
        elif prop == "terminal":
            x, y = side * 44.0, -25.0
            rounded_rect(cr, x - 14, y, 28, 21, 3.8)
            paint(cr, rgb("#211C27"), rgb("#4D4557"), lw=2.0)
            for i, col in enumerate(("#FB7185", "#FBBF24", "#4ADE80")):
                ellipse(cr, x - 10 + i * 3.6, y + 3.6, 1.15, 1.15)
                paint(cr, rgb(col))
            row = int(p.prop_t * 2.2) % 3
            green = rgb("#4ADE80")
            for i in range(row):
                cr.new_path()
                cr.move_to(x - 10, y + 8.4 + i * 3.6)
                cr.line_to(x - 10 + (11 if i % 2 == 0 else 7), y + 8.4 + i * 3.6)
                stroke(cr, rgb("#8F879B"), 1.3)
            cy = y + 8.4 + row * 3.6
            cr.new_path()
            cr.move_to(x - 10, cy - 1.5)
            cr.line_to(x - 7.8, cy)
            cr.line_to(x - 10, cy + 1.5)
            stroke(cr, green, 1.4)
            if int(p.prop_t * 3.0) % 2 == 0:
                rounded_rect(cr, x - 5.6, cy - 1.6, 3.4, 3.2, 0.6)
                paint(cr, green)
        elif prop == "globe":
            x = side * 45.0
            y = -56.0 + math.sin(p.prop_t * 2.0) * 2.0
            r = 10.0
            ellipse(cr, x, y, r, r)
            cr.save()
            cr.clip()
            src(cr, rgb("#38BDF8"))
            cr.paint()
            shift = (p.prop_t * 7.0) % (r * 4)
            land = rgb("#4ADE80")
            for bx, byy, brx, bry in ((-8, -3, 5.5, 4.2), (4, 3.5, 6, 3.6), (14, -4.5, 4.6, 3.4),
                                      (24, 2.5, 5.2, 4)):
                for rep in (0, r * 4):
                    ellipse(cr, x - r * 2 + (bx + shift + rep) % (r * 4) - 2, y + byy, brx, bry)
                    paint(cr, land)
            cr.restore()
            ellipse(cr, x, y, r, r)
            paint(cr, None, rgb("#1D6FA3"), lw=1.9)
            cr.new_path()
            cr.arc(x - 3, y - 3, 5.6, math.pi * 1.1, math.pi * 1.5)
            stroke(cr, WHITE, 1.5, 0.7)
        elif prop == "gear":
            x, y = side * 45.0, -54.0
            cr.save()
            cr.translate(x, y)
            cr.rotate(p.prop_t * 1.8)
            teeth, r_out, r_in = 8, 10.0, 7.4
            cr.new_path()
            for i in range(teeth):
                a0 = i * TAU / teeth
                for j, (da, r) in enumerate(((0.0, r_in), (0.1, r_out), (0.3, r_out), (0.4, r_in))):
                    a = a0 + da * TAU / teeth * 1.9
                    px, py = math.cos(a) * r, math.sin(a) * r
                    if i == 0 and j == 0:
                        cr.move_to(px, py)
                    else:
                        cr.line_to(px, py)
            cr.close_path()
            paint(cr, rgb("#B9C0CC"), rgb("#5B5568"), lw=1.8)
            ellipse(cr, 0, 0, 3.0, 3.0)
            paint(cr, rgb("#5B5568"))
            cr.restore()

    def overhead_marks(self):
        cr, p = self.cr, self.p
        top = self.head_cy - self.head_ry - p.lift + p.bob
        if "cloud" in p.marks:
            cx, cy = self.head_cx, top - 20
            grey = rgb("#9AA3B2")
            for i in range(3):
                fall = (p.t * 1.4 + i * 0.33) % 1.0
                cr.new_path()
                cr.move_to(cx - 9 + i * 9, cy + 6 + fall * 12)
                cr.line_to(cx - 10.5 + i * 9, cy + 10 + fall * 12)
                stroke(cr, TEAR_D, 1.6, 1 - fall)
            cr.new_path()
            ellipse(cr, cx - 8, cy + 1, 7.5, 6)
            ellipse(cr, cx + 1, cy - 3, 9, 7.5)
            ellipse(cr, cx + 10, cy + 1.5, 7, 5.5)
            src(cr, outline_of(grey))
            cr.set_line_width(3.2)
            cr.stroke_preserve()
            src(cr, grey)
            cr.fill()
        if "dizzy" in p.marks:
            cx, cy = self.head_cx, top - 4
            for i in range(3):
                a = p.t * 4.0 + i * TAU / 3
                x, y = cx + math.cos(a) * 20, cy + math.sin(a) * 5.5
                star_path(cr, x, y, 4.0, 1.7, 5, a)
                paint(cr, GOLD, outline_of(GOLD), lw=1.1,
                      alpha=0.55 + 0.45 * (math.sin(a) > -0.2))

    # -- ghost ----------------------------------------------------------

    def ghost(self):
        cr, p, k = self.cr, self.p, self.k
        f = p.facing
        float_y = -5.0 + math.sin(p.t * 2.6) * 2.0 + p.sit * 2.0 + p.lie * 4.0
        cr.save()
        cr.translate(p.head_dx, float_y + p.head_dy)
        if p.head_tilt:
            cr.rotate(p.head_tilt * 0.6)
        top = -80.0 + p.lie * 16
        rx = 27.0 + p.lie * 3
        hem = -4.0
        wave = p.t * 2.6
        cr.new_path()
        cr.move_to(-rx, -44 + p.lie * 8)
        cr.curve_to(-rx, top + 6, -rx * 0.62, top, 0, top)
        cr.curve_to(rx * 0.62, top, rx, top + 6, rx, -44 + p.lie * 8)
        cr.line_to(rx, hem)
        n = 4
        for i in range(n):
            x0 = rx - (2 * rx) * i / n
            x1 = rx - (2 * rx) * (i + 1) / n
            dip = 5.5 + math.sin(wave + i * 1.7) * 2.0
            cr.curve_to(x0 - (x0 - x1) * 0.25, hem + dip, x1 + (x0 - x1) * 0.25, hem + dip, x1, hem)
        cr.close_path()
        paint(cr, k.fur, k.line, alpha=0.96)
        for side, angle in ((-1, p.arm_l), (1, p.arm_r)):
            sx, sy = side * (rx - 2), -36 + p.lie * 6
            ex = sx + side * math.sin(angle) * 9
            ey = sy + math.cos(angle) * 9
            tube(cr, ((sx, sy), (ex, ey)), 6.5, k.fur, k.line)
        cr.translate(0, -52 + p.lie * 12)
        self.eye_y = 0.0
        if not self.flat:
            self.face(f)
        self.head_accessory(f)
        if p.hat and p.hat != "headphones":
            cr.translate(0, -3)
            self.hat(p.hat)
            cr.translate(0, 3)
        if not self.flat:
            self.face_marks(f)
        cr.restore()


class _Silhouette:
    """Cairo context stand-in that draws every shape in one flat colour, grown
    by ``grow`` on all sides — one cheap extra pass gives the sticker border."""

    def __init__(self, cr, color, grow, alpha=1.0):
        self._cr = cr
        self._rgb = color
        self._grow = grow * 2.0
        self._alpha = alpha
        for name in ("save", "restore", "translate", "rotate", "scale", "move_to", "line_to", "curve_to",
                     "arc", "new_path", "new_sub_path", "close_path", "clip", "stroke", "paint",
                     "set_line_cap", "set_line_join", "select_font_face", "set_font_size", "text_extents",
                     "show_text", "stroke_preserve", "rectangle", "copy_path", "append_path"):
            setattr(self, name, getattr(cr, name))

    def set_source_rgba(self, r, g, b, a=1.0):
        c = self._rgb
        self._cr.set_source_rgba(c[0], c[1], c[2], a * self._alpha)

    def set_line_width(self, width):
        self._cr.set_line_width(width + self._grow)

    def fill(self):
        cr = self._cr
        cr.set_line_width(self._grow)
        cr.fill_preserve()
        cr.stroke()

    def fill_preserve(self):
        cr = self._cr
        cr.set_line_width(self._grow)
        cr.fill_preserve()
        cr.stroke_preserve()

    def __getattr__(self, name):
        return getattr(self._cr, name)


def draw_pet(cr, design, pose, rim=None, shadow=True):
    """Draw a pet at the origin (ground point) in pet units.

    ``rim`` is ``(colour, width)``: a sticker-style border drawn around the
    whole silhouette so the pet stays readable on any background.
    """
    if rim:
        if shadow:
            _Painter(cr, design, pose).shadow()
        _Painter(_Silhouette(cr, rim[0], rim[1]), design, pose, flat=True).draw(shadow=False)
        _Painter(cr, design, pose).draw(shadow=False)
    else:
        _Painter(cr, design, pose).draw(shadow=shadow)
    if pose.flash > 0.02:
        # Electrocution gag: the whole figure flashes white, bones showing.
        _Painter(_Silhouette(cr, WHITE, 0.0, alpha=min(1.0, pose.flash)), design, pose, flat=True).draw(shadow=False)
        if pose.flash > 0.45:
            ghost = _Painter(cr, design, pose)
            cr.save()
            cr.translate(0, pose.bob - pose.lift)
            if pose.lean:
                cr.rotate(pose.lean)
            _human.xray(ghost)
            cr.restore()


def draw_shadow(cr, design, pose):
    _Painter(cr, design, pose).shadow()


def draw_silhouette(cr, design, pose, grow):
    """The pet's outline grown by ``grow``, as plain coverage (for a mask)."""
    _Painter(_Silhouette(cr, WHITE, grow), design, pose, flat=True).draw(shadow=False)


def pet_extents(pose=None):
    """Loose bounding box of a standing pet in pet units: (x0, y0, x1, y1)."""
    return (-46.0, -104.0, 46.0, 8.0)


from . import human as _human  # noqa: E402  (needs the helpers above)
