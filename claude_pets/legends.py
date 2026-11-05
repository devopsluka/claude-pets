"""Legends: characters that are not pets and do not want to be petted.

Each has a *signature move* that replaces petting — poke Mike and he throws a
punch, Snoop takes a drag, Pablo does a line, Einstein has an idea, Tesla
throws lightning — and the same move shows up where it fits the session:
Mike punches a failing command, Tesla gets zapped by one, Einstein lights up
when thinking turns into doing, Pablo asks "plata o plomo?" for a permission.

A :class:`Trait` only decorates what the ordinary brain already does, so a
legend still shows the same honest status as any pet (laptop, book, sign…).
"""

import math

from .model import Activity as A
from .model import Signal as S
from .render.creature import HEAD_CY, SPECIES

HANDS_BUSY = ("laptop", "book", "clipboard", "magnifier", "sign", "flag")


def ease(t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def mouth_point(pet, p):
    """Where the character's mouth is, in pet units (for hand-to-mouth moves)."""
    spec = SPECIES.get(pet.design.species, {})
    y = HEAD_CY + p.sit * 4.0 + p.lie * 13.0 + p.head_dy + spec.get("eye_y", 3.0) + 10.8
    return (p.facing * 8.0 + 4.5 + p.head_dx, y)


def set_hand(p, side, point):
    if side > 0:
        p.hand_r = point
    else:
        p.hand_l = point


class Trait:
    """What makes a character itself. This base class is an ordinary pet."""

    legend = False
    poke_label = "Pet {name}"
    idle = {}                  # extra idle actions: name -> weight
    idle_time = {}             # name -> (min seconds, max seconds)
    drop_idle = ()             # pet-ish idle actions this character never does
    lively = frozenset()       # idle actions that need a fast repaint
    lines = {}

    def signature(self, pet, now):
        """Do the move that replaces being petted. False = just a pet."""
        return False

    def after_signal(self, pet, name, data, state):
        pass

    def pose_idle(self, pet, p, name, t, k, dt):
        return False

    def decorate_work(self, pet, p, kind, t, dt):
        pass

    def decorate_alert(self, pet, p, waited):
        pass

    def decorate_done(self, pet, p, t):
        pass

    def decorate(self, pet, p, dt):
        pass

    def react(self, pet, p, name, k, data):
        pass

    def visit(self, pet, friend):
        return False

    def line(self, key, default=""):
        return self.lines.get(key, default)


# ----------------------------------------------------------------------------

class Tyson(Trait):
    legend = True
    poke_label = "Make {name} throw a punch"
    idle = {"shadowbox": 5, "flex": 1}
    idle_time = {"shadowbox": (3.0, 5.5), "flex": (1.8, 2.6)}
    drop_idle = ("groom", "hum", "hop")
    lively = frozenset({"shadowbox"})
    lines = {"hi": "The baddest man on the desktop", "bye": "Lights out. Bye.",
             "streak": "Everybody has a plan until exit code 1", "done": "And still… the champ!"}

    def _target(self, pet):
        best = None
        for other in pet.world.others(pet):
            gap = abs(other.x - pet.x)
            if gap < 120 * pet.world.scale and not other.held and not other.airborne:
                if best is None or gap < abs(best.x - pet.x):
                    best = other
        return best

    def signature(self, pet, now):
        victim = self._target(pet)
        direction = (1.0 if victim.x > pet.x else -1.0) if victim else pet.prop_side
        pet.start_sig("punch", 0.95, dir=direction, target=victim)
        return True

    def after_signal(self, pet, name, data, state):
        if name == S.TOOL_ERROR:
            pet.start_sig("punch", 0.8, dir=pet.prop_side)
            if int(data.get("streak") or 1) >= 3:
                pet.say(self.lines["streak"], "error", emoji="🥊")
        elif name == S.TESTS_PASSED:
            pet.start_sig("punch", 0.8, dir=pet.prop_side, text="K.O.!")
        elif name == S.TURN_DONE and pet.done_big and pet.bubble:
            pet.say("%s  %s" % (self.lines["done"], pet.bubble.get("plain", "")), "success", ttl=6.5,
                    emoji="🥊", important=True)

    def react(self, pet, p, name, k, data):
        if name != "punch":
            return
        d = data.get("dir", 1.0)
        pet.face_to = d * 0.9
        p.brow, p.mouth, p.ear = "angry", "teeth", 0.4
        guard = (-d * 9.0, -33.0)
        if k < 0.28:                               # wind up
            e = ease(k / 0.28)
            fist = (d * (15 - 9 * e), -27.0)
            p.lean = -d * 0.10 * e
        elif k < 0.58:                             # the punch lands
            e = ease((k - 0.28) / 0.12)
            fist = (d * (10 + 30 * e), -26.0)
            p.lean = d * 0.17 * e
            p.squash = -0.12 * e
            if e >= 1.0 and not data.get("hit"):
                data["hit"] = True
                pet.fx.pow(d * 50, -30, data.get("text", "POW!"))
                victim = data.get("target")
                if victim is not None and not victim.gone:
                    victim.knocked(d)
        else:                                      # back to guard
            e = ease((k - 0.58) / 0.42)
            fist = (d * (40 - 27 * e), -26.0 - 4 * e)
            p.lean = d * 0.17 * (1 - e)
        set_hand(p, d, fist)
        set_hand(p, -d, guard)

    def pose_idle(self, pet, p, name, t, k, dt):
        if name == "shadowbox":
            side = 1.0 if math.sin(t * 0.9) >= 0 else -1.0
            pet.face_to = side * 0.8
            beat = (t * 2.6) % 2.0
            jab = beat % 1.0
            lead = side if beat < 1.0 else -side
            reach = math.sin(min(1.0, jab / 0.35) * math.pi) if jab < 0.35 else 0.0
            set_hand(p, lead, (side * (11 + 24 * reach) if lead == side else side * (4 + 22 * reach), -28.0))
            set_hand(p, -lead, (-side * 3.0 if -lead == side else side * 6.0, -33.0))
            p.bob = -abs(math.sin(t * 8.0)) * 1.6
            p.lean = side * 0.05 + math.sin(t * 2.6) * 0.03
            p.brow, p.mouth = "angry", "flat"
            return True
        if name == "flex":
            up = math.sin(min(1.0, k * 2.0) * math.pi * 0.5)
            p.arm_l = p.arm_r = 0.35 + 2.0 * up
            p.eye, p.mouth = "closed", "grin"
            p.squash = -0.08 * up
            return True
        return False

    def decorate_done(self, pet, p, t):
        if pet.done_big:
            p.prop = "belt"
            p.arm_l = p.arm_r = 2.45 + math.sin(t * 5.0) * 0.12
            p.eye, p.mouth = "happy", "grin"

    def visit(self, pet, friend):
        if pet.rng.random() < 0.7:
            direction = 1.0 if friend.x > pet.x else -1.0
            pet.start_sig("punch", 1.0, dir=direction, target=friend)
            return True
        return False


class Snoop(Trait):
    legend = True
    poke_label = "Pass {name} the lighter"
    idle = {"toke": 6, "sway": 2}
    idle_time = {"toke": (3.4, 3.4), "sway": (3.0, 5.0)}
    drop_idle = ("groom", "hop", "stretch")
    lines = {"hi": "Whaddup — it's the D-O-double-G", "bye": "Peace out, nephew",
             "streak": "That ain't it, chief", "done": "Fo shizzle."}

    def signature(self, pet, now):
        pet.start_sig("toke", 3.4)
        return True

    def after_signal(self, pet, name, data, state):
        if name == S.TURN_DONE and pet.bubble:
            pet.say("%s  %s" % (self.lines["done"], pet.bubble.get("plain", "")), "success", ttl=6.0,
                    emoji="💨", important=True)
        elif name == S.TOOL_ERROR and int(data.get("streak") or 1) >= 3:
            pet.say(self.lines["streak"], "error", emoji="😎")

    def toke(self, pet, p, k, data):
        """Drag, hold, long exhale."""
        mx, my = mouth_point(pet, p)
        rest = (17.0, -13.0)
        p.item, p.item_at = "joint", "hand"
        if k < 0.12:
            e = ease(k / 0.12)
            p.hand_r = (rest[0] + (mx + 3 - rest[0]) * e, rest[1] + (my - rest[1]) * e)
            p.item_glow = 0.3
        elif k < 0.42:
            p.hand_r = (mx + 3, my)
            p.item_glow = 0.6 + 0.4 * math.sin((k - 0.12) / 0.30 * math.pi)
            p.blush = 1.0
            p.mouth = "o"
            p.mouth_open = 0.3
        elif k < 0.55:
            e = ease((k - 0.42) / 0.13)
            p.hand_r = (mx + 3 + (rest[0] - mx - 3) * e, my + (rest[1] - my) * e)
            p.item_glow = 0.3
            p.mouth = "flat"
            p.head_tilt = -0.06 * e
            p.blush = 1.0
        elif k < 0.95:
            p.item_glow = 0.25
            p.mouth = "o"
            p.mouth_open = 1.0
            p.head_tilt = -0.08
            p.lean = -0.03
            step = int((k - 0.55) / 0.035)
            if data.get("puff") != step:
                data["puff"] = step
                pet.fx.smoke(mx + 2, my - 1, 1.0 if p.facing >= -0.2 else -1.0, big=step % 3 == 0)
        else:
            p.item_glow = 0.25

    def react(self, pet, p, name, k, data):
        if name == "toke":
            self.toke(pet, p, k, data)

    def pose_idle(self, pet, p, name, t, k, dt):
        if name == "toke":
            self.toke(pet, p, k, pet.idle_data)
            return True
        if name == "sway":
            p.lean = math.sin(t * 2.4) * 0.07
            p.head_tilt = math.sin(t * 2.4 + 0.7) * 0.08
            p.bob = -abs(math.sin(t * 4.8)) * 0.8
            p.mouth = "grin"
            pet.emit_t -= dt
            if pet.emit_t <= 0:
                pet.emit_t = 0.9
                pet.fx.note()
            return True
        return False

    def decorate_work(self, pet, p, kind, t, dt):
        if kind == A.THINKING:
            cycle = t % 7.0
            if cycle < 3.4 and t > 0.4:
                p.arm_r = 0.35
                self.toke(pet, p, cycle / 3.4, pet.__dict__.setdefault("_think_toke", {}))

    def decorate(self, pet, p, dt):
        if pet.asleep or p.held or p.item:
            return
        busy = p.prop in HANDS_BUSY or p.arm_r > 1.2 or p.hand_r is not None or p.arm_fwd_r > 0.3
        p.item, p.item_at, p.item_glow = "joint", ("mouth" if busy else "hand"), 0.25


class Pablo(Trait):
    legend = True
    poke_label = "Cut {name} a line"
    idle = {"waiting": 5, "cash": 2, "line": 1}
    idle_time = {"waiting": (6.0, 12.0), "cash": (3.5, 5.5), "line": (2.5, 2.5)}
    drop_idle = ("groom", "hop", "hum", "stretch")
    lines = {"hi": "Hola. Soy Pablo.", "bye": "Hasta luego.", "alert": "Plata o plomo?",
             "streak": "¡Ay, no! Otra vez…", "done": "Negocio cerrado."}

    def signature(self, pet, now):
        pet.start_sig("line", 2.5)
        return True

    def after_signal(self, pet, name, data, state):
        if name == S.PROMPT and data.get("sentiment", "neutral") == "neutral":
            if state.energy < 0.45 or pet.rng.random() < 0.35:
                pet.start_sig("line", 2.5)
        elif name == S.TURN_DONE and pet.done_big:
            pet.fx.items = [x for x in pet.fx.items if x.kind != "confetti"]
            pet.fx.bills()
            if pet.bubble:
                pet.say("%s  %s" % (self.lines["done"], pet.bubble.get("plain", "")), "success", ttl=6.5,
                        emoji="💵", important=True)
        elif name == S.TOOL_ERROR and int(data.get("streak") or 1) >= 3:
            pet.say(self.lines["streak"], "error", emoji="😤")

    def line_move(self, pet, p, k, data):
        """Down to the mirror, along the line, and back up wide awake."""
        p.prop = "mirror"
        if k < 0.18:
            e = ease(k / 0.18)
            p.sit, p.head_dy, p.prop_t = 0.7 * e, 15.0 * e, 0.0
            p.look = (0.0, 1.0)
        elif k < 0.62:
            u = (k - 0.18) / 0.44
            p.sit, p.head_dy = 0.7, 15.0
            p.head_dx = -8.0 + 16.0 * u
            p.prop_t = u
            p.eye = "closed"
        elif k < 0.74:
            e = ease((k - 0.62) / 0.12)
            p.sit, p.head_dy = 0.7 * (1 - e), 15.0 * (1 - e) - 2.0 * e
            p.prop_t = 1.0
            p.lift = math.sin(e * math.pi) * 5.0
            p.eye, p.mouth = "wide", "o"
        else:
            p.prop_t = 1.0
            p.eye, p.mouth = "sparkle", "teeth"
            p.head_dx = math.sin(pet.t * 45.0) * 1.0
            p.ear = 1.0
            if not data.get("up"):
                data["up"] = True
                pet.fx.sparkles(6, 0, -52, 30)
                pet.wired_until = pet.world.now + 14.0

    def react(self, pet, p, name, k, data):
        if name == "line":
            self.line_move(pet, p, k, data)

    def pose_idle(self, pet, p, name, t, k, dt):
        if name == "waiting":                      # the lonely-Pablo stare
            p.arm_l = p.arm_r = 0.05
            p.head_dy = 2.5
            p.look = (math.sin(t * 0.35) * 0.5, 0.75)
            p.brow, p.mouth = "sad", "flat"
            p.lean = math.sin(t * 0.8) * 0.02
            return True
        if name == "cash":
            p.item, p.item_at = "bills", "hand"
            p.arm_r = 1.15 + math.sin(t * 7.0) * 0.12
            p.look = (0.6, 0.4)
            p.eye, p.mouth = "happy", "grin"
            return True
        if name == "line":
            self.line_move(pet, p, k, pet.idle_data)
            return True
        return False

    def decorate_alert(self, pet, p, waited):
        if waited > 40:
            p.prop = ""
            p.lift = 0.0
            p.squash = 0.0
            p.arm_l = p.arm_r = 0.05
            p.head_dy = 2.5
            p.look = (0.0, 0.75)
            p.brow, p.mouth, p.eye = "sad", "flat", "open"

    def decorate(self, pet, p, dt):
        if pet.world.now < getattr(pet, "wired_until", 0.0) and not pet.asleep and not p.held and not pet.react:
            p.head_dx += math.sin(pet.t * 43.0) * 0.9
            p.bob += math.sin(pet.t * 37.0) * 0.5
            if p.eye == "open":
                p.eye = "wide"
            if p.mouth in ("smile", "flat"):
                p.mouth = "teeth"
            p.prop_t *= 2.2
            p.marks = frozenset(p.marks) | {"sweat"}


class Einstein(Trait):
    legend = True
    poke_label = "Give {name} an idea"
    idle = {"ponder": 5, "tongue": 1}
    idle_time = {"ponder": (5.0, 9.0), "tongue": (1.6, 2.2)}
    drop_idle = ("groom", "hop")
    lines = {"hi": "Guten Tag! Albert here.", "bye": "Time is relative. Bye!",
             "streak": "Same command, expecting a new result?", "done": "Eureka!"}

    def signature(self, pet, now):
        pet.start_sig("eureka", 1.9)
        return True

    def after_signal(self, pet, name, data, state):
        now = pet.world.now
        if name == S.TOOL_START:
            thought = getattr(pet, "think_t", 0.0)
            pet.think_t = 0.0
            if thought >= 2.5 and now - getattr(pet, "last_eureka", -99.0) > 25.0 and not pet.react:
                pet.last_eureka = now
                pet.start_sig("eureka", 1.6)
        elif name == S.TURN_DONE:
            if not pet.done_big:
                pet.start_sig("eureka", 1.7)
            if pet.bubble:
                pet.say("%s  %s" % (self.lines["done"], pet.bubble.get("plain", "")), "success", ttl=6.0,
                        emoji="💡", important=True)
        elif name == S.TOOL_ERROR and int(data.get("streak") or 1) >= 3:
            pet.say(self.lines["streak"], "error", emoji="🤔")

    def react(self, pet, p, name, k, data):
        if name != "eureka":
            return
        p.item, p.item_at = "bulb", "over"
        p.item_glow = min(1.0, k * 7.0) * (0.85 + 0.15 * math.sin(pet.t * 30.0))
        p.arm_r = 2.75
        p.eye, p.mouth, p.ear = "sparkle", "grin", 1.0
        p.lift = math.sin(min(1.0, k * 3.0) * math.pi) * 6.0
        if not data.get("fx"):
            data["fx"] = True
            pet.fx.sparkles(5, 0, -96, 26)

    def decorate_work(self, pet, p, kind, t, dt):
        if kind == A.THINKING:
            pet.think_t = t
            side = pet.prop_side
            p.prop, p.prop_t = "chalkboard", t
            pet.face_to = side * 0.75
            p.arm_r = p.arm_l = 0.35
            if (t % 4.0) < 2.6:
                set_hand(p, side, (side * 31.0, -46.0 + math.sin(t * 9.0) * 3.0))
            else:
                set_hand(p, -side, None)
                if side > 0:
                    p.arm_l = 2.3 + math.sin(t * 11.0) * 0.13
                else:
                    p.arm_r = 2.3 + math.sin(t * 11.0) * 0.13
            p.look = (side * 0.8, -0.3)

    def decorate_done(self, pet, p, t):
        if t < 3.5:
            p.mouth, p.eye = "tongue", "wide"       # that photo

    def pose_idle(self, pet, p, name, t, k, dt):
        if name == "ponder":
            span = 44.0 * pet.world.scale
            leg = int(t / 3.2) % 2
            target = pet.world.clamp_x(pet.home_x + (span if leg == 0 else -span))
            pet._walk(p, dt, target, 22.0)
            p.arm_l = p.arm_r = 0.05
            p.head_dy = 1.5
            p.look = (p.facing * 0.5, 0.7)
            p.mouth = "flat"
            return True
        if name == "tongue":
            p.mouth, p.eye = "tongue", "wide"
            p.head_tilt = 0.1
            return True
        return False


class Tesla(Trait):
    legend = True
    poke_label = "Give {name} a spark"
    idle = {"sparks": 5, "pigeon": 2}
    idle_time = {"sparks": (3.0, 5.0), "pigeon": (5.0, 9.0)}
    drop_idle = ("groom", "hop", "hum")
    lively = frozenset({"sparks"})
    lines = {"hi": "Good day. Tesla.", "bye": "The future is mine. Farewell.",
             "streak": "This smells like Edison's work", "done": "It works — wirelessly."}
    COIL_KINDS = (A.RUNNING, A.TESTING, A.TOOL, A.BROWSING)

    def signature(self, pet, now):
        pet.start_sig("lightning", 1.6)
        return True

    def after_signal(self, pet, name, data, state):
        if name == S.TOOL_ERROR:
            pet.start_sig("zap", 1.1)
            if int(data.get("streak") or 1) >= 3:
                pet.say(self.lines["streak"], "error", emoji="⚡")
        elif name == S.TESTS_PASSED:
            pet.start_sig("lightning", 1.3)
        elif name == S.TURN_DONE and pet.bubble:
            pet.say("%s  %s" % (self.lines["done"], pet.bubble.get("plain", "")), "success", ttl=6.0,
                    emoji="⚡", important=True)

    def react(self, pet, p, name, k, data):
        color = None
        if name == "lightning":
            up = ease(min(1.0, k * 5.0)) * (1.0 if k < 0.85 else ease((1.0 - k) / 0.15))
            p.hand_l = (-13.0 - 9.0 * up, -24.0 - 20.0 * up)
            p.hand_r = (13.0 + 9.0 * up, -24.0 - 20.0 * up)
            p.eye, p.mouth, p.ear = "sparkle", "grin", 1.0
            p.shock = 0.25 < k < 0.8
            p.bob = math.sin(pet.t * 40.0) * 0.5
            step = int(k / 0.06)
            if data.get("step") != step and 0.12 < k < 0.88:
                data["step"] = step
                pet.fx.arc(p.hand_l[0], p.hand_l[1], p.hand_r[0], p.hand_r[1], color)
                pet.fx.bolts(1, 0, -50, 46)
                if step == 4:
                    for other in pet.world.others(pet):
                        if abs(other.x - pet.x) < 95 * pet.world.scale:
                            other.zapped()
        elif name == "zap":
            fry = k < 0.7
            p.shock = True
            p.eye, p.mouth = ("wide", "teeth") if fry else ("spiral", "wavy")
            if fry:
                p.flash = 0.92 if int(k * 14) % 2 == 0 else 0.12
                p.head_dx = math.sin(pet.t * 60.0) * 1.4
                p.arm_l = p.arm_r = 1.6
                step = int(k / 0.07)
                if data.get("step") != step:
                    data["step"] = step
                    pet.fx.bolts(2, 0, -44, 40)
            elif not data.get("smoke"):
                data["smoke"] = True
                pet.fx.smoke(0, -84, 1.0, n=3, big=True)

    def decorate_work(self, pet, p, kind, t, dt):
        side = pet.prop_side
        if kind in self.COIL_KINDS:
            p.prop, p.prop_t = "coil", t
            p.arm_l = p.arm_r = 0.35
            p.foot_l = p.foot_r = (0.0, 0.0)
            pet.face_to = side * 0.7
            hand = (side * 27.0, -30.0 + math.sin(t * 6.0) * 2.0)
            set_hand(p, side, hand)
            p.look = (side, -0.3)
            if kind != A.TESTING:
                p.eye, p.mouth = "open", "smile"
            pet.emit_t -= dt
            if pet.emit_t <= 0:
                pet.emit_t = 0.45
                pet.fx.arc(side * 38.0, -37.0, hand[0], hand[1])
        elif kind == A.WRITING:
            pet.emit_t -= dt
            if pet.emit_t <= 0:
                pet.emit_t = 1.1
                x = pet.rng.choice((-15.0, 15.0))
                pet.fx.arc(x, -22.0, x + pet.rng.uniform(-7, 7), -34.0)

    def decorate_done(self, pet, p, t):
        p.prop = ""
        p.item, p.item_at = "bulb", "hand"
        p.item_glow = 0.8 + 0.2 * math.sin(t * 8.0)
        p.arm_r = 1.9
        p.eye, p.mouth = "happy", "grin"

    def pose_idle(self, pet, p, name, t, k, dt):
        if name == "sparks":
            p.hand_l, p.hand_r = (-13.0, -29.0 + math.sin(t * 3.0)), (13.0, -29.0 - math.sin(t * 3.0))
            p.eye, p.mouth = "sparkle", "grin"
            p.look = (0.0, 0.6)
            pet.emit_t -= dt
            if pet.emit_t <= 0:
                pet.emit_t = 0.13
                pet.fx.arc(p.hand_l[0], p.hand_l[1], p.hand_r[0], p.hand_r[1])
            return True
        if name == "pigeon":
            p.item, p.item_at = "pigeon", "over"
            p.look = (0.0, -1.0)
            p.eye, p.mouth = "happy", "smile"
            p.head_tilt = math.sin(t * 1.2) * 0.04
            return True
        return False


PLAIN = Trait()
TRAITS = {"tyson": Tyson(), "snoop": Snoop(), "pablo": Pablo(), "einstein": Einstein(), "tesla": Tesla()}


def trait_for(species):
    return TRAITS.get(species, PLAIN)
