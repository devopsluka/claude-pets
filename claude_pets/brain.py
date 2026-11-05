"""Pet brain: turns a session's state, its feelings and the passing of time
into behaviour — where the pet goes, what it does, the face it makes.

No GTK in here: a :class:`Pet` only produces a ``Pose``, particles and a
bubble each frame, so it can be simulated and rendered off-screen.
"""

import math
import random
import zlib

from . import legends
from . import voice as voice_mod
from .model import Activity as A
from .model import Emotion as E
from .model import Signal as S
from .render.creature import GRAB_Y, SPECIES, Pose
from .render.fx import GREEN, Particles

GRAVITY = 2600.0        # px/s²
WALK_SPEED = 40.0       # pet units / s
RUN_SPEED = 130.0
INF = float("inf")

EMOJI = {
    A.LISTENING: "👂", A.THINKING: "💭", A.READING: "📖", A.SEARCHING: "🔍", A.WRITING: "✏️",
    A.RUNNING: "⚡", A.TESTING: "🧪", A.BROWSING: "🌐", A.DELEGATING: "👷", A.PLANNING: "📋",
    A.TOOL: "🔧", A.COMPACTING: "🗜️",
}
FEELING = {
    E.CONTENT: "feeling content", E.HAPPY: "feeling happy", E.JOYFUL: "over the moon",
    E.PROUD: "proud of that one", E.FOCUSED: "in the zone", E.CURIOUS: "curious about this",
    E.DETERMINED: "determined to get it right", E.TIRED: "getting tired", E.SLEEPY: "sleepy",
    E.BORED: "a little bored", E.STRESSED: "stressed", E.FRUSTRATED: "frustrated",
    E.SAD: "feeling down", E.ANXIOUS: "anxiously waiting for you", E.SICK: "under the weather",
    E.STUFFED: "stuffed — context is nearly full",
}
#: default face per emotion: (eye, mouth, brow, blush, ear, marks)
FACES = {
    E.CONTENT: ("open", "smile", "", 0.45, 0.0, ()),
    E.HAPPY: ("open", "smile", "", 0.65, 0.3, ()),
    E.JOYFUL: ("happy", "grin", "", 0.85, 0.6, ()),
    E.PROUD: ("closed", "smile", "", 0.7, 0.4, ()),
    E.FOCUSED: ("open", "flat", "", 0.35, 0.2, ()),
    E.CURIOUS: ("open", "o", "raised", 0.5, 0.8, ()),
    E.DETERMINED: ("open", "flat", "angry", 0.3, 0.3, ()),
    E.TIRED: ("sleepy", "flat", "", 0.3, -0.5, ()),
    E.SLEEPY: ("sleepy", "flat", "", 0.4, -0.4, ()),
    E.BORED: ("sleepy", "flat", "", 0.3, -0.2, ()),
    E.STRESSED: ("open", "wavy", "sad", 0.3, -0.3, ("sweat",)),
    E.FRUSTRATED: ("open", "teeth", "angry", 0.2, -0.2, ("anger",)),
    E.SAD: ("open", "frown", "sad", 0.3, -1.0, ()),
    E.ANXIOUS: ("open", "wavy", "sad", 0.35, -0.6, ("sweat",)),
    E.SICK: ("sleepy", "wavy", "sad", 0.2, -0.8, ("thermo", "bandage")),
    E.STUFFED: ("sleepy", "wavy", "", 0.9, -0.2, ()),
}
IDLE_WEIGHTS = {
    "default": dict(stand=3, sit=3, walk=2, look=2, groom=2, hum=1, visit=1, stretch=1),
    E.HAPPY: dict(stand=2, sit=1, walk=3, look=1, hop=2, hum=3, visit=3),
    E.JOYFUL: dict(walk=2, hop=4, hum=3, visit=3, stand=1),
    E.PROUD: dict(stand=3, hum=3, walk=2, hop=1, visit=2, sit=1),
    E.BORED: dict(walk=3, look=2, sit=2, stretch=2, yawn=2, hum=1, visit=2),
    E.TIRED: dict(sit=4, yawn=3, stand=1),
    E.SAD: dict(sulk=4, sit=2, stand=1, walk=1),
    E.STRESSED: dict(sulk=2, sit=2, stand=2, walk=2),
    E.FRUSTRATED: dict(sulk=3, stand=2, walk=2),
    E.SICK: dict(sit=4, sulk=1),
    E.STUFFED: dict(sit=4, stand=1, yawn=1),
}
PERSONALITY_BIAS = {
    "playful": dict(hop=2, visit=2, walk=1), "calm": dict(sit=2, stand=1), "curious": dict(look=3, walk=2),
    "sleepy": dict(yawn=2, sit=2), "brave": dict(walk=2, hop=1), "shy": dict(sit=1, look=1, visit=-1),
    "snarky": dict(look=2, stand=1, visit=-1, hop=-2),
}
MAX_MINIS = 4
SLEEP_LOOP = math.tau / 1.3     # seconds; matches the renderer's slow idle motions
SLEEP_FRAMES = 20


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm %02ds" % (seconds // 60, seconds % 60)
    return "%dh %02dm" % (seconds // 3600, (seconds % 3600) // 60)


class World:
    """The strip of desktop the pets live on (all values in screen px)."""

    def __init__(self, left, top, right, floor, scale=1.0, config=None, rng=None):
        self.left, self.top, self.right, self.floor = float(left), float(top), float(right), float(floor)
        self.scale = float(scale)          # px per pet unit
        self.config = config or {}
        self.rng = rng or random.Random()
        self.pets = []
        self.now = 0.0

    @property
    def width(self):
        return self.right - self.left

    def clamp_x(self, x):
        margin = 42.0 * self.scale
        return clamp(x, self.left + margin, self.right - margin)

    def free_home(self, pet):
        """A resting spot near the bottom-right corner that nobody else uses."""
        gap = 108.0 * self.scale
        taken = [p.home_x for p in self.pets if p is not pet and not p.leaving]
        x = self.right - 96.0 * self.scale
        for _ in range(40):
            if all(abs(x - t) >= gap * 0.8 for t in taken):
                break
            x -= gap
            if x < self.left + 60 * self.scale:
                x = self.rng.uniform(self.left + 80, self.right - 80)
                break
        return self.clamp_x(x)

    def others(self, pet):
        return [p for p in self.pets if p is not pet and not p.leaving and p.phase == "live"]


class Pet:
    def __init__(self, key, profile, world, now, entrance="pop"):
        self.key = key
        self.profile = profile
        self.world = world
        self.rng = random.Random(zlib.crc32(str(key).encode("utf-8")))      # same pet, same quirks, every run
        self.session = None
        self.fx = Particles(self.rng)
        self.pose = Pose()
        self.bubble = None
        self.t = self.rng.uniform(0, 10)
        w = world
        if profile.home >= 0:
            self.home_x = w.clamp_x(w.left + profile.home * w.width)
            for other in w.pets:
                if other is not self and abs(other.home_x - self.home_x) < 70 * w.scale:
                    self.home_x = w.free_home(self)
                    break
        else:
            self.home_x = w.free_home(self)
        self.x = self.home_x
        self.y = self._rest_y()
        self.vx = self.vy = 0.0
        self.held = False
        self.airborne = False
        self.dangle = self.dangle_v = 0.0
        self.hold_target = (self.x, self.y)
        self.facing = 0.0
        self.face_to = 0.0
        self.tail_side = -1.0
        self.walk_phase = 0.0
        self.moving = False
        self.phase = "appear"              # appear | enter | live | leave
        self.phase_t = 0.0
        self.appear = 0.0                  # 0..1 pop-in scale
        self.leaving = False
        self.gone = False
        self.mode = "idle"                 # idle | work | alert | done | sick
        self.mode_t = 0.0
        self.work_kind = ""
        self.idle = "stand"
        self.idle_t = 0.0
        self.idle_dur = self.rng.uniform(1.5, 3.5)
        self.idle_data = {}
        self.react = None                  # [name, t, duration, data]
        self.asleep = False
        self.blink_in = self.rng.uniform(1.0, 4.0)
        self.blink_t = -1.0
        self.land_t = 1.0
        self.hover = False
        self.pointer = None                # pointer in pet units, relative to the ground point
        self.prop_side = 1.0
        self.emit_t = 0.0
        self.sleep_step = 0
        self.minis = 0
        self.last_petted = -INF
        self.dirty_profile = False
        self.want_focus = False
        self.first_seen = now
        if entrance == "walk":
            edge_left = (self.home_x - w.left) < (w.right - self.home_x)
            self.x = (w.left - 60 * w.scale) if edge_left else (w.right + 60 * w.scale)
            self.phase = "enter"
            self.appear = 1.0
        elif entrance == "hatch":
            self.fx.sparkles(8, 0, -44, 40)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @property
    def name(self):
        return self.profile.name

    @property
    def design(self):
        return self.profile.design

    @property
    def trait(self):
        """The character's signature behaviour (a plain pet has none)."""
        return legends.trait_for(self.profile.design.species)

    def start_sig(self, move, duration, **data):
        """Start one of the character's own reactions."""
        if self.held or self.airborne or self.phase != "live":
            return
        data["name"] = move
        self.react = ["sig", 0.0, duration, data]
        self.asleep = False

    def knocked(self, direction):
        """Somebody landed a punch on this one (it will be fine)."""
        if self.held or self.airborne or self.phase != "live":
            return
        self.asleep = False
        self.react = ["dizzy", 0.0, 1.8, {}]
        self.x = self.world.clamp_x(self.x + direction * 18.0 * self.world.scale)
        self.fx.stars(4, 0, -44)
        self.land_t = 0.0

    def zapped(self):
        """Caught some stray lightning."""
        if self.held or self.airborne or self.phase != "live":
            return
        self.asleep = False
        self.react = ["zapped", 0.0, 0.9, {}]

    def _rest_y(self):
        w = self.world
        if not w.config.get("gravity", True) and self.profile.perch >= 0:
            return clamp(w.top + self.profile.perch * (w.floor - w.top), w.top + 110 * w.scale, w.floor)
        return w.floor

    def cfg(self, key, default=None):
        return self.world.config.get(key, default)

    def say(self, text, style="say", ttl=3.2, sticky=False, important=False, emoji="", voice="", **fields):
        """Show a speech bubble. ``voice`` names the line so a personality with its own
        voice (see ``voice.py``) can word it differently; ``fields`` fill its blanks."""
        mode = self.cfg("bubbles", "all")
        if mode == "off" or (mode == "important" and not important):
            return
        if voice:
            text = voice_mod.line(self.profile.personality, voice, self.rng, text, **fields)
        plain = text
        if emoji and self.cfg("emoji", True):
            text = "%s %s" % (emoji, text)
        now = self.world.now
        same = self.bubble and self.bubble["text"] == text and self.bubble["style"] == style
        self.bubble = {
            "text": text, "plain": plain, "style": style, "t0": self.bubble["t0"] if same else now,
            "until": INF if sticky else now + ttl, "sticky": sticky,
        }

    def hush(self, sticky_only=False):
        if self.bubble and (self.bubble["sticky"] or not sticky_only):
            self.bubble["until"] = min(self.bubble["until"], self.world.now + 0.2)
            self.bubble["sticky"] = False

    def start_react(self, name, duration, **data):
        if self.held or self.airborne or self.phase != "live":
            return
        self.react = [name, 0.0, duration, data]
        if self.asleep and name not in ("love",):
            self.asleep = False

    # ------------------------------------------------------------------
    # session events
    # ------------------------------------------------------------------

    def on_session(self, state, signals):
        self.session = state
        self.minis = min(MAX_MINIS, max(0, state.subagents))
        prof = self.profile
        for name, data in signals:
            data = data or {}
            if name == S.SESSION_START:
                source = data.get("source", "")
                if source == "clear":
                    self.fx.sparkles(6)
                    self.say("Fresh start!", "info", emoji="✨", voice="fresh")
                elif source in ("startup", "resume"):
                    prof.bump("sessions")
                    self.dirty_profile = True
            elif name == S.PROMPT:
                sentiment = data.get("sentiment", "neutral")
                if sentiment == "praise":
                    self.start_react("love", 1.8)
                    self.fx.hearts(4)
                    self.say(self.rng.choice(("Aww, thanks!", "Yay!", "Happy to help!")), "success", emoji="💛",
                             voice="praise")
                elif sentiment == "frustrated":
                    self.start_react("sheepish", 1.8)
                    self.say(self.rng.choice(("On it…", "Let me fix that.", "Sorry! Looking…")), "say", emoji="💦",
                             voice="frustrated")
                else:
                    self.start_react("perk", 0.55)
            elif name == S.TOOL_START:
                if not state.needs_user:
                    self._announce(state)
            elif name == S.TOOL_OK:
                prof.bump("tools")
                self._xp(1)
                streak = int(data.get("streak") or 0)
                if streak in (10, 25, 50, 100):
                    self.start_react("hop", 0.5)
                    self.fx.sparkles(4)
                    self.say("On a roll ×%d" % streak, "success", emoji="🔥", voice="streak_ok", n=streak)
            elif name == S.TOOL_ERROR:
                streak = int(data.get("streak") or 1)
                self.start_react("flinch", 0.7)
                self.fx.cross()
                if streak >= 3:
                    self.fx.steam()
                    self.say("%d failures in a row…" % streak, "error", emoji="😤", voice="streak_err", n=streak)
            elif name == S.TESTS_PASSED:
                self.start_react("cheer", 1.2)
                self.fx.check()
                self.fx.sparkles(5)
                self.say("Tests passed!", "success", emoji="✅", important=True, voice="tests_passed")
                self._xp(5)
            elif name == S.TESTS_FAILED:
                self.say("Tests failed", "error", emoji="❌", important=True, voice="tests_failed")
            elif name == S.COMMIT:
                self.start_react("cheer", 1.2)
                self.fx.check()
                self.say("Committed!", "success", emoji="📦", important=True, voice="commit")
                self._xp(5)
            elif name == S.NEEDS_USER:
                reason = data.get("reason", "")
                if reason == "idle":
                    self.say("Your turn!", "info", ttl=6.0, emoji="👋", important=True, voice="your_turn")
                else:
                    self.start_react("startle", 0.5)
                    self._alert_bubble(state)
            elif name == S.USER_RESPONDED:
                self.hush(sticky_only=True)
                self.start_react("hop", 0.45)
            elif name == S.PERMISSION_DENIED:
                self.start_react("sheepish", 1.6)
                self.say("Okay, not that.", "say", emoji="🙈", voice="denied")
            elif name == S.TURN_DONE:
                self._turn_done(state, data)
            elif name == S.TURN_FAILED:
                self.hush()
                self.start_react("dizzy", 1.6)
                error = str(data.get("error") or "API error").replace("_", " ")
                self.say("Ouch — %s" % error, "error", ttl=8.0, emoji="🤒", important=True, voice="turn_failed",
                         error=error)
            elif name == S.INTERRUPTED:
                self.hush()
                self.start_react("startle", 0.5)
                self.say("Oh! Stopping.", "say", emoji="✋", voice="interrupted")
            elif name == S.SUBAGENT_START:
                count = int(data.get("count") or 1)
                self.fx.sparkles(3)
                self.say("Calling in helpers ×%d" % count if count > 1 else "Calling in a helper", "say",
                         emoji="👷", voice="helpers" if count > 1 else "helper", n=count)
            elif name == S.COMPACT_START:
                self.say("Squeezing my memory…", "info", ttl=6.0, emoji="🗜️", important=True, voice="compact")
            elif name == S.COMPACT_DONE:
                self.fx.sparkles(5)
                self.say("Much lighter!", "success", emoji="✨", voice="compact_done")
            elif name == S.TASK_COMPLETED:
                self.fx.check()
            elif name == S.CONTEXT_HIGH:
                pct = data.get("pct") or state.context_pct or 0.8
                self.say("Getting full… %d%% context" % round(pct * 100), "alert", ttl=6.0, emoji="🍙",
                         important=True, voice="context_high", pct=round(pct * 100))
            elif name == S.SESSION_END:
                self.leave()
            self.trait.after_signal(self, name, data, state)
        if state.ended:
            self.leave()

    def _xp(self, amount):
        level = self.profile.add_xp(amount)
        self.dirty_profile = True
        if level:
            self.start_react("cheer", 1.4)
            self.fx.sparkles(8)
            self.fx.pop_text("LEVEL %d!" % level, GREEN, size=11.5, life=2.2)

    def _announce(self, state):
        text = state.detail
        if not text:
            return
        now = self.world.now
        if (voice_mod.has_voice(self.profile.personality) and now - self.last_aside > voice_mod.ASIDE_EVERY
                and self.rng.random() < voice_mod.ASIDE_CHANCE):
            self.last_aside = now
            self.say(text, "say", ttl=4.2, emoji=EMOJI.get(state.activity, ""), voice="aside", detail=text)
            return
        self.say(text, "say", ttl=3.6, emoji=EMOJI.get(state.activity, ""))

    last_aside = -999.0

    def _alert_bubble(self, state):
        reason = state.needs_reason
        if reason == "question":
            self.say("I have a question for you", "alert", sticky=True, emoji="❓", important=True, voice="question")
        elif reason == "elicitation":
            self.say("I need your input", "alert", sticky=True, emoji="❓", important=True, voice="input")
        else:
            detail = state.needs_detail or state.detail
            ask = self.trait.line("alert", "") or voice_mod.line(self.profile.personality, "permission", self.rng,
                                                                 "Need your OK")
            text = ask + (" · %s" % detail if detail else "")
            self.say(text, "alert", sticky=True, emoji="✋", important=True)

    def _turn_done(self, state, data):
        self.hush()
        duration = float(data.get("duration") or 0.0)
        tools = int(data.get("tools") or 0)
        errors = int(data.get("errors") or 0)
        self.profile.bump("turns")
        self._xp(10 if not errors else 5)
        opener = voice_mod.line(self.profile.personality, "done_errors" if errors else "done", self.rng, "Done")
        parts = [opener]
        if duration >= 5:
            parts.append(fmt_duration(duration))
        if tools:
            parts.append("%d tool%s" % (tools, "" if tools == 1 else "s"))
        big = tools >= 3 or duration >= 25
        if errors:
            self.start_react("phew", 1.5)
            self.say(" · ".join(parts), "success", ttl=6.0, emoji="😮‍💨", important=True)
        elif big:
            self.start_react("celebrate", 1.9)
            self.fx.confetti()
            self.say(" · ".join(parts), "success", ttl=6.5, emoji="✅", important=True)
        else:
            self.start_react("hop", 0.5)
            self.say(" · ".join(parts), "success", ttl=4.5, emoji="✅", important=True)
        self.done_big = big and not errors

    done_big = False

    # ------------------------------------------------------------------
    # user interaction
    # ------------------------------------------------------------------

    def petted(self, now):
        """A click: the pet enjoys it. Returns True when it counts as new affection."""
        fresh = now - self.last_petted > 1.2
        self.last_petted = now
        if self.trait.legend:
            # Legends are not pets: instead of purring they do their thing.
            if not self.react or self.react[0] != "sig":
                self.trait.signature(self, now)
        else:
            self.fx.hearts(2 if self.asleep else 3)
            if not self.asleep:
                self.start_react("love", 1.4)
        if fresh:
            self.profile.bump("pets")
            self._xp(1)
        return fresh

    def treat(self):
        self.profile.bump("treats")
        self.dirty_profile = True
        self.start_react("munch", 2.2)
        self.say("Nom nom!", "success", emoji="🍪")

    def grab(self, px, py):
        self.held = True
        self.airborne = False
        self.asleep = False
        self.react = None
        self.moving = False
        self.hold_target = (px, py)
        self.dangle_v = 0.0

    def drag_to(self, px, py):
        self.hold_target = (px, py)

    def release(self, vx, vy):
        if not self.held:
            return
        self.held = False
        w = self.world
        if w.config.get("gravity", True):
            self.airborne = True
            self.vx = clamp(vx, -1600, 1600)
            self.vy = clamp(vy, -1600, 1600)
        else:
            self.y = clamp(self.y, w.top + 110 * w.scale, w.floor)
            self.profile.perch = (self.y - w.top) / max(1.0, w.floor - w.top)
            self._settle_home()

    def _settle_home(self):
        w = self.world
        self.x = w.clamp_x(self.x)
        self.home_x = self.x
        self.profile.home = (self.x - w.left) / max(1.0, w.width)
        self.dirty_profile = True

    def leave(self):
        if self.leaving:
            return
        self.leaving = True
        self.phase = "leave"
        self.phase_t = 0.0
        self.react = None
        self.held = self.airborne = False
        self.say(self.trait.line("bye", "Bye!"), "say", ttl=1.6, emoji="👋")

    # ------------------------------------------------------------------
    # frame update
    # ------------------------------------------------------------------

    def desired_fps(self):
        """How often this pet needs repainting right now.

        Sprite pets animate at 4-9 frames a second; ours get more when they
        really move and very little when they are calm, because every frame
        costs the X server and the compositor some work too.
        """
        if self.held or self.airborne or self.react or self.phase != "live" or self.land_t < 1.0:
            return 30
        if self.bubble and (self.world.now - self.bubble["t0"] < 0.3 or self.bubble["until"] - self.world.now < 0.1):
            return 30
        if self.moving:
            base = 20
        elif self.mode == "alert":
            base = 16
        elif self.asleep:
            base = 4
        elif self.mode in ("work", "done", "sick"):
            base = 10
        elif self.mode == "idle" and self.idle in ("stand", "sit", "sulk"):
            base = 6
        elif self.idle == "hop" or self.idle in self.trait.lively:
            base = 24
        else:
            base = 12
        if self.blink_t >= 0:
            base = max(base, 15)
        return max(base, self.fx.fps())

    def update(self, dt, now):
        dt = min(dt, 0.1)
        self.t += dt
        self.phase_t += dt
        self.mode_t += dt
        p = Pose(t=self.t)
        self.moving = False
        if self.held:
            self._update_held(p, dt)
        elif self.airborne:
            self._update_fall(p, dt)
        elif self.phase == "appear":
            self.appear = min(1.0, self.phase_t / 0.42)
            p.eye, p.mouth = "happy", "grin"
            if self.appear >= 1.0:
                self.phase, self.phase_t = "live", 0.0
                self.start_react("wave", 1.3)
        elif self.phase == "enter":
            arrived = self._walk(p, dt, self.home_x, RUN_SPEED)
            p.eye, p.mouth = "happy", "grin"
            if arrived:
                self.phase, self.phase_t = "live", 0.0
                self.start_react("wave", 1.4)
                self.say(self.trait.line("hi", "Hi! I'm %s" % self.name), "say", ttl=3.0, emoji="👋")
        elif self.phase == "leave":
            self._react_wave(p, (self.phase_t * 1.4) % 1.0, {})
            if self.phase_t > 1.4:
                self.appear = max(0.0, 1.0 - (self.phase_t - 1.4) / 0.3)
                if self.appear <= 0.0:
                    self.gone = True
        else:
            self._update_live(p, dt, now)
        if self.land_t < 1.0:
            self.land_t = min(1.0, self.land_t + dt / 0.38)
            k = self.land_t
            p.squash += (1 - k) * 0.85 * math.cos(k * math.pi * 1.5)
        self._micro(p, dt)
        self.fx.update(dt)
        if self.bubble and now >= self.bubble["until"] + 0.25:
            self.bubble = None
        self.pose = p

    # -- held / falling ---------------------------------------------------

    def _update_held(self, p, dt):
        w = self.world
        tx, ty = self.hold_target
        grab_dy = -GRAB_Y * w.scale
        nx = self.x + (tx - self.x) * min(1.0, dt * 22)
        ny = self.y + (ty + grab_dy - self.y) * min(1.0, dt * 22)
        vx = (nx - self.x) / max(dt, 1e-3)
        self.vx, self.vy = vx, (ny - self.y) / max(dt, 1e-3)
        self.x, self.y = nx, ny
        target = clamp(-vx / 900.0, -0.75, 0.75)
        self.dangle_v += ((target - self.dangle) * 60.0 - self.dangle_v * 7.0) * dt
        self.dangle += self.dangle_v * dt
        p.held = True
        p.dangle = self.dangle
        p.squash = -0.28
        p.arm_l = p.arm_r = 0.12
        sway = self.dangle * 6
        p.foot_l = (-2 + sway, 3.5)
        p.foot_r = (2 + sway, 3.5)
        p.tail = clamp(self.dangle * 2.5, -1, 1)
        if self.profile.personality in ("playful", "brave") and self.phase_t > 0.5:
            p.eye, p.mouth = "happy", "grin"
        else:
            p.eye, p.mouth = "wide", "o"
        p.ear = -0.4

    def _update_fall(self, p, dt):
        w = self.world
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        lo, hi = w.left + 30 * w.scale, w.right - 30 * w.scale
        if self.x < lo:
            self.x, self.vx = lo, abs(self.vx) * 0.5
        elif self.x > hi:
            self.x, self.vx = hi, -abs(self.vx) * 0.5
        self.dangle *= max(0.0, 1 - dt * 8)
        p.lean = clamp(self.vx / 2500.0, -0.35, 0.35)
        p.squash = -0.3
        p.arm_l = p.arm_r = 2.5
        p.eye, p.mouth = "wide", "o"
        p.foot_l, p.foot_r = (-1, 2.5), (1, 2.5)
        if self.y >= w.floor:
            impact = self.vy
            self.y = w.floor
            if impact > 520 and abs(self.vy) > 0:
                self.vy = -impact * 0.28
                self.vx *= 0.6
                self.fx.dust(0, 4)
                self.land_t = 0.0
                if impact > 1500:
                    self.fx.stars(4)
                    self.hit_hard = True
            else:
                self.airborne = False
                self.vx = self.vy = 0.0
                self.land_t = 0.0
                self.fx.dust(0, 3)
                self._settle_home()
                if getattr(self, "hit_hard", False):
                    self.hit_hard = False
                    self.react = ["dizzy", 0.0, 1.7, {}]
                self.idle, self.idle_t, self.idle_dur = "stand", 0.0, 1.5

    hit_hard = False

    # -- alive and well ---------------------------------------------------

    def _target_mode(self):
        s = self.session
        if s is None:
            return "idle", ""
        a = s.activity
        if a in A.NEEDS_USER or (s.needs_user and s.needs_reason in ("permission", "question", "elicitation")):
            return "alert", s.needs_reason or "permission"
        if a in A.WORKING:
            return "work", a
        if a == A.DONE:
            return "done", ""
        if a == A.FAILED:
            return "sick", ""
        return "idle", ""

    def _update_live(self, p, dt, now):
        mode, kind = self._target_mode()
        if mode != self.mode or kind != self.work_kind:
            was_asleep = self.asleep
            if mode != self.mode:
                self.mode_t = 0.0
                if mode != "idle":
                    self.asleep = False
                    if was_asleep:
                        self.react = ["startle", 0.0, 0.5, {}]
                        self.fx.pop_text("!", size=13.0, life=0.8)
                if mode == "alert" and self.session and not (self.bubble and self.bubble["sticky"]):
                    self._alert_bubble(self.session)
                if self.mode == "alert":
                    self.hush(sticky_only=True)
                if mode == "idle":
                    self.idle, self.idle_t, self.idle_dur = "stand", 0.0, self.rng.uniform(1.5, 3.0)
            elif mode == "work":
                self.mode_t = min(self.mode_t, 0.35) if kind != self.work_kind else self.mode_t
            self.mode, self.work_kind = mode, kind
            centre = (self.world.left + self.world.right) / 2.0
            self.prop_side = 1.0 if self.x < centre else -1.0
        p.prop_side = self.prop_side

        if self.react:
            name, t, dur, data = self.react
            t += dt
            self.react[1] = t
            if t >= dur:
                self.react = None
            else:
                getattr(self, "_react_" + name)(p, t / dur, data)
                self.trait.decorate(self, p, dt)
                return
        trait = self.trait
        if self.mode == "work":
            self._pose_work(p, dt)
            trait.decorate_work(self, p, self.work_kind, self.mode_t, dt)
        elif self.mode == "alert":
            self._pose_alert(p, now)
            s = self.session
            trait.decorate_alert(self, p, max(0.0, now - s.needs_since) if (s and s.needs_since) else self.mode_t)
        elif self.mode == "done":
            self._pose_done(p)
            trait.decorate_done(self, p, self.mode_t)
        elif self.mode == "sick":
            self._pose_sick(p)
        else:
            self._pose_idle(p, dt, now)
        self._apply_emotion(p)
        trait.decorate(self, p, dt)

    def _apply_emotion(self, p):
        s = self.session
        emotion = s.emotion if s else E.CONTENT
        eye, mouth, brow, blush, ear, marks = FACES.get(emotion, FACES[E.CONTENT])
        if self.asleep:
            return
        if p.eye == "open" and eye != "open":
            p.eye = eye
        if p.mouth == "smile" and mouth != "smile":
            p.mouth = mouth
        if not p.brow:
            p.brow = brow
        p.blush = blush
        if p.ear == 0.0:
            p.ear = ear
        if marks:
            p.marks = frozenset(p.marks) | frozenset(marks)
        if s is not None:
            pct = s.context_pct or 0.0
            if pct > 0.6:
                p.belly = clamp((pct - 0.6) / 0.35, 0.0, 1.0)
            if emotion == E.SAD and s.mood < 0.15:
                p.marks = frozenset(p.marks) | {"tear"}
            if emotion == E.FOCUSED and not p.hat and self.mode == "work":
                p.hat = "headphones"
            if emotion == E.TIRED and self.mode == "work" and not p.prop:
                p.prop = "mug"

    # -- work ---------------------------------------------------------------

    def _pose_work(self, p, dt):
        a = self.work_kind
        t = self.mode_t
        ease = min(1.0, t * 4.0)
        side = self.prop_side
        p.prop_t = t
        if a == A.LISTENING:
            p.ear = 1.0
            p.look = (0.0, -0.5)
            p.head_tilt = 0.09 * math.sin(t * 3.0)
            p.eye_open = 1.0
        elif a == A.THINKING:
            p.sit = 0.5 * ease
            p.look = (-0.55 + 0.25 * math.sin(t * 0.7), -0.85)
            p.head_tilt = -0.09
            cycle = t % 3.4
            if cycle < 1.7:
                p.arm_r = 2.3 + math.sin(t * 11.0) * 0.13
            p.mouth = "flat"
            if self.bubble is None and self.cfg("bubbles", "all") == "all" and t > 0.6:
                dots = "· " * (1 + int(t * 1.6) % 3)
                self.bubble = {"text": dots.strip(), "style": "think", "t0": self.world.now - 1,
                               "until": self.world.now + 0.5, "sticky": False}
            elif self.bubble and self.bubble["style"] == "think":
                self.bubble["text"] = ("· " * (1 + int(t * 1.6) % 3)).strip()
                self.bubble["until"] = self.world.now + 0.5
        elif a == A.READING:
            p.sit = ease
            p.prop = "book"
            p.glasses = True
            scan = (t * 0.9) % 1.0
            p.look = (-0.7 + 1.4 * scan, 0.85)
            p.head_dx = (-0.7 + 1.4 * scan) * 0.8
        elif a == A.SEARCHING:
            p.prop = "magnifier"
            p.arm_r = 1.95
            sweep = math.sin(t * 1.25)
            p.lean = sweep * 0.05
            p.head_tilt = sweep * 0.09
            self.face_to = sweep * 0.8
            p.look = (sweep * 0.8, 0.3)
            p.ear = 0.8
        elif a == A.WRITING:
            p.sit = ease
            p.prop = "laptop"
            p.look = (math.sin(t * 2.3) * 0.35, 0.75)
            p.head_dy = abs(math.sin(t * 9.0)) * 0.7
            p.mouth = "tongue" if int(t / 3.5) % 3 == 1 else "smile"
            p.arm_l = 0.2 + abs(math.sin(t * 9.0)) * 0.12
            p.arm_r = 0.2 + abs(math.cos(t * 9.0)) * 0.12
        elif a in (A.RUNNING, A.TESTING):
            p.prop = "terminal"
            self.face_to = 0.75 * side
            p.look = (side, 0.5)
            poke = 1.05 + math.sin(t * 7.0) * 0.25
            if side > 0:
                p.arm_r = poke
            else:
                p.arm_l = poke
            if t > 8.0:
                tap = -abs(math.sin(t * 6.0)) * 2.2
                if side > 0:
                    p.foot_l = (0.0, tap)
                else:
                    p.foot_r = (0.0, tap)
            if a == A.TESTING:
                p.eye, p.mouth = "wide", "wavy"
                p.bob = math.sin(t * 6.0) * 0.6
        elif a == A.BROWSING:
            p.prop = "globe"
            self.face_to = 0.6 * side
            p.look = (side, -0.8)
            p.head_tilt = -0.07 * side
            p.mouth = "o"
            p.ear = 1.0
        elif a == A.DELEGATING:
            p.hat = "hardhat"
            call = math.sin(t * 0.8)
            self.face_to = call * 0.7
            if call > 0:
                p.arm_r = 1.75 + math.sin(t * 5.0) * 0.2
            else:
                p.arm_l = 1.75 + math.sin(t * 5.0) * 0.2
            p.mouth = "grin"
            p.mouth_open = 0.5 + 0.5 * math.sin(t * 8.0)
        elif a == A.PLANNING:
            p.sit = 0.4 * ease
            p.prop = "clipboard"
            p.look = (0.1, 0.85)
            p.arm_fwd_r = 0.75 + 0.1 * math.sin(t * 8.0)
        elif a == A.COMPACTING:
            p.squash = 0.35 + 0.3 * math.sin(t * 7.0)
            p.eye, p.mouth = "squeeze", "teeth"
            p.marks = frozenset({"sweat"})
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit_t = 0.5
                self.fx.papers(2)
        else:                               # generic tool
            p.prop = "gear"
            self.face_to = 0.6 * side
            p.look = (side, -0.6)
            crank = 1.3 + math.sin(t * 5.0) * 0.3
            if side > 0:
                p.arm_r = crank
            else:
                p.arm_l = crank

    def _pose_alert(self, p, now):
        s = self.session
        waited = max(0.0, now - s.needs_since) if (s and s.needs_since) else self.mode_t
        question = bool(s) and s.needs_reason in ("question", "elicitation")
        side = self.prop_side
        p.prop = "sign"
        p.prop_text = "?" if question else "!"
        p.prop_t = self.mode_t
        if side > 0:
            p.arm_r = 2.25
        else:
            p.arm_l = 2.25
        self.face_to = 0.0
        p.look = (0.0, -0.25)
        period = 2.4 if waited < 30 else 1.5 if waited < 150 else 3.6
        k = (self.mode_t % period) / 0.5
        if k < 1.0:
            p.lift = math.sin(k * math.pi) * (11.0 if waited < 150 else 6.0)
            p.squash = -0.2 * math.sin(k * math.pi)
        if question:
            p.head_tilt = 0.12 * math.sin(self.mode_t * 2.0)
            p.mouth = "o"
        elif waited < 45:
            p.eye, p.mouth = "wide", "o"
        else:
            p.brow, p.mouth = "sad", "wavy"
            p.marks = frozenset({"sweat"})
        if s and self.bubble is None and int(self.mode_t) % 12 == 6:
            self._alert_bubble(s)

    def _pose_done(self, p):
        t = self.mode_t
        if self.done_big:
            p.prop = "flag"
            p.prop_t = t
            p.arm_r = 1.0
            p.eye, p.mouth = "happy", "grin"
            p.lean = math.sin(t * 2.2) * 0.035
            p.ear = 0.8
        else:
            p.eye = "happy"
            p.lean = math.sin(t * 2.0) * 0.02

    def _pose_sick(self, p):
        t = self.mode_t
        p.sit = min(1.0, t * 3)
        p.ear = -1.0
        p.mouth = "none"
        p.marks = frozenset({"thermo", "bandage"} | ({"dizzy"} if t < 3.0 else set()))
        p.eye = "spiral" if t < 3.0 else "sleepy"
        p.lean = math.sin(t * 1.2) * 0.03

    # -- idle ---------------------------------------------------------------

    def _pick_idle(self, now):
        s = self.session
        emotion = s.emotion if s else E.CONTENT
        idle_for = (now - s.activity_since) if s else 0.0
        sleepy = emotion == E.SLEEPY or idle_for >= float(self.cfg("sleep_after", 600))
        if sleepy:
            if self.idle in ("yawn", "sleep"):
                return "sleep", INF, {}
            return "yawn", 1.8, {}
        weights = dict(IDLE_WEIGHTS.get(emotion, IDLE_WEIGHTS["default"]))
        for key, bonus in PERSONALITY_BIAS.get(self.profile.personality, {}).items():
            if key in weights or bonus > 0:
                weights[key] = max(0, weights.get(key, 0) + bonus)
        if SPECIES.get(self.design.species, {}).get("tail") not in ("cat", "fox", "puff"):
            weights.pop("groom", None)
        trait = self.trait
        for key in trait.drop_idle:
            weights.pop(key, None)
        if emotion != E.SICK:
            for key, weight in trait.idle.items():
                weights[key] = weights.get(key, 0) + weight
        if not self.cfg("wander", True) or not self.cfg("gravity", True):
            weights.pop("walk", None)
            weights.pop("visit", None)
        if not self.cfg("social", True) or not self._friends():
            weights.pop("visit", None)
        weights.pop(self.idle, None) if len(weights) > 1 else None
        names = list(weights)
        choice = self.rng.choices(names, [max(0.01, weights[n]) for n in names])[0]
        r = self.rng
        w = self.world
        if choice == "walk":
            reach = 150.0 * w.scale
            target = w.clamp_x(self.home_x + r.uniform(-reach, reach))
            return "walk", 12.0, {"x": target}
        if choice == "visit":
            friend = r.choice(self._friends())
            offset = 62.0 * w.scale * (1 if self.x > friend.x else -1)
            return "visit", 20.0, {"friend": friend, "x": w.clamp_x(friend.x + offset)}
        durations = dict(stand=(2.0, 5.0), sit=(4.0, 10.0), look=(2.0, 3.5), groom=(2.2, 3.4), hum=(3.0, 5.0),
                         stretch=(1.8, 1.8), hop=(0.5, 0.5), yawn=(1.8, 1.8), sulk=(4.0, 9.0))
        durations.update(trait.idle_time)
        lo, hi = durations.get(choice, (2.0, 4.0))
        return choice, r.uniform(lo, hi), {}

    def _friends(self):
        return [o for o in self.world.others(self) if o.mode == "idle" and not o.asleep and not o.held
                and not o.airborne and abs(o.x - self.x) < 900 * self.world.scale]

    def _pose_idle(self, p, dt, now):
        self.idle_t += dt
        if self.idle_t >= self.idle_dur:
            self.idle, self.idle_dur, self.idle_data = self._pick_idle(now)
            self.idle_t = 0.0
            self.asleep = self.idle == "sleep"
        t = self.idle_t
        k = t / self.idle_dur if self.idle_dur not in (0, INF) else 0.0
        name = self.idle
        if name == "walk":
            if self._walk(p, dt, self.idle_data["x"], WALK_SPEED):
                self.idle_dur = 0.0
        elif name == "visit":
            friend = self.idle_data["friend"]
            if friend.gone or friend.leaving or friend.mode != "idle" or friend.held:
                self.idle_dur = 0.0
            elif self._walk(p, dt, self.idle_data["x"], WALK_SPEED * 1.25):
                self.face_to = 1.0 if friend.x > self.x else -1.0
                if not self.trait.visit(self, friend):
                    friend.greeted_by(self)
                    self.react = ["greet", 0.0, 2.6, {"dir": self.face_to}]
                self.idle_dur = 0.0
        elif name == "sit":
            p.sit = min(1.0, t * 3.0) * (1.0 if self.idle_dur - t > 0.3 else max(0.0, (self.idle_dur - t) / 0.3))
            p.look = (math.sin(self.t * 0.6) * 0.5, 0.0)
        elif name == "look":
            sweep = math.sin(t * 2.2)
            self.face_to = sweep
            p.look = (sweep, -0.2)
            p.ear = 0.7
        elif name == "groom":
            p.sit = min(1.0, t * 3.0)
            p.arm_r = 2.1 + math.sin(t * 9.0) * 0.18
            p.head_tilt = 0.14
            p.eye, p.mouth = "closed", "tongue"
        elif name == "hum":
            p.eye = "happy"
            p.lean = math.sin(t * 3.2) * 0.06
            p.head_tilt = math.sin(t * 3.2 + 0.6) * 0.07
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit_t = 0.8
                self.fx.note()
        elif name == "stretch":
            if k < 0.55:
                up = math.sin(k / 0.55 * math.pi)
                p.squash = -0.45 * up
                p.arm_l = p.arm_r = 0.35 + 2.2 * up
                p.eye, p.mouth = "closed", "yawn"
                p.mouth_open = up
            else:
                p.squash = 0.3 * math.sin((k - 0.55) / 0.45 * math.pi)
                p.eye = "closed"
        elif name == "hop":
            p.lift = math.sin(k * math.pi) * 12.0
            p.squash = -0.2 * math.sin(k * math.pi)
            p.eye, p.mouth = "happy", "grin"
        elif name == "yawn":
            up = math.sin(clamp(k, 0, 1) * math.pi)
            p.eye, p.mouth = "closed", "yawn"
            p.mouth_open = up
            p.arm_r = 0.35 + 1.7 * up
            p.head_tilt = -0.08 * up
        elif name == "sleep":
            p.lie = min(1.0, t * 1.6)
            p.eye, p.mouth = "closed", "o"
            p.hat = "nightcap"
            p.ear = -0.5
            # Sleep is one slow loop of SLEEP_FRAMES poses, so a napping pet
            # can be replayed from cached frames instead of being redrawn.
            step = int(t / SLEEP_LOOP * SLEEP_FRAMES) % SLEEP_FRAMES
            angle = step * math.tau / SLEEP_FRAMES
            p.t = angle / 1.3
            p.mouth_open = 0.3 + 0.3 * math.sin(angle + 1.0)
            self.sleep_step = step
            self.emit_t -= dt
            if self.emit_t <= 0:
                self.emit_t = 1.7
                self.fx.zzz(14 * (1 if self.tail_side < 0 else -1))
        elif name == "sulk":
            p.sit = min(1.0, t * 2.5)
            self.face_to = -0.6 * self.prop_side
            p.look = (-self.prop_side * 0.6, 0.8)
            p.head_dy = 2.0
            p.marks = frozenset({"gloom"})
        elif self.trait.pose_idle(self, p, name, t, k, dt):
            pass
        else:                               # stand
            p.look = (math.sin(self.t * 0.5) * 0.6, math.sin(self.t * 0.37) * 0.3)
            if abs(self.face_to) > 0.5:
                self.face_to *= 0.98

    def greeted_by(self, other):
        """Another pet walked over to say hi."""
        if self.mode != "idle" or self.held or self.airborne or self.asleep or self.react:
            return
        direction = 1.0 if other.x > self.x else -1.0
        self.react = ["greet", 0.0, 2.6, {"dir": direction, "delay": 0.35}]
        self.idle, self.idle_t, self.idle_dur = "stand", 0.0, 3.5

    def cheer_for(self, other):
        """A nearby friend just finished something big."""
        if self.mode != "idle" or self.asleep or self.react or self.held or self.airborne or self.phase != "live":
            return
        self.react = ["cheer", 0.0, 1.2, {"dir": 1.0 if other.x > self.x else -1.0}]
        self.fx.note()

    # -- reactions ------------------------------------------------------------

    def _react_wave(self, p, k, data):
        p.arm_r = 2.45 + math.sin(k * math.pi * 6) * 0.32
        p.eye, p.mouth = "happy", "grin"
        p.head_tilt = 0.06 * math.sin(k * math.pi * 6)
        p.ear = 0.8

    def _react_greet(self, p, k, data):
        direction = data.get("dir", 1.0)
        self.face_to = direction * 0.9
        delay = data.get("delay", 0.0)
        kk = clamp((k * 2.6 - delay) / (2.6 - delay), 0.0, 1.0)
        if kk <= 0:
            return
        if direction > 0:
            p.arm_r = 2.45 + math.sin(kk * math.pi * 7) * 0.3
        else:
            p.arm_l = 2.45 + math.sin(kk * math.pi * 7) * 0.3
        p.eye, p.mouth = "happy", "grin"
        p.lift = max(0.0, math.sin(kk * math.pi * 3)) * 4.0
        if not data.get("fx") and kk > 0.3:
            data["fx"] = True
            self.fx.hearts(1, direction * 26, -58)
            self.fx.note(direction * 10)

    def _react_perk(self, p, k, data):
        up = math.sin(k * math.pi)
        p.ear = 1.0
        p.lift = up * 4.0
        p.eye_open = 1.0
        p.look = (0.0, -0.5)

    def _react_hop(self, p, k, data):
        up = math.sin(k * math.pi)
        p.lift = up * 12.0
        p.squash = -0.22 * up
        p.eye, p.mouth = "happy", "grin"
        p.arm_l = p.arm_r = 0.35 + up * 1.2

    def _react_cheer(self, p, k, data):
        if "dir" in data:
            self.face_to = data["dir"] * 0.7
        phase = (k * 2.0) % 1.0
        up = math.sin(phase * math.pi)
        p.lift = up * 13.0
        p.squash = -0.2 * up
        p.arm_l = p.arm_r = 2.2 + up * 0.4
        p.eye, p.mouth = "sparkle", "grin"
        p.ear = 1.0

    def _react_celebrate(self, p, k, data):
        phase = (k * 2.0) % 1.0
        up = math.sin(phase * math.pi)
        p.lift = up * 19.0
        p.squash = -0.3 * up + (0.25 if phase < 0.08 or phase > 0.92 else 0.0)
        p.arm_l = p.arm_r = 2.35 + up * 0.35
        p.eye, p.mouth = "sparkle", "grin"
        p.hat = "party"
        p.ear = 1.0
        p.lean = math.sin(k * math.pi * 4) * 0.06

    def _react_phew(self, p, k, data):
        p.eye, p.mouth = "closed", "o"
        p.mouth_open = math.sin(k * math.pi)
        p.arm_r = 2.2 + math.sin(k * math.pi * 3) * 0.2
        p.squash = 0.15 * math.sin(k * math.pi)
        p.ear = -0.3

    def _react_flinch(self, p, k, data):
        hit = math.sin(min(1.0, k * 2.2) * math.pi)
        p.squash = 0.55 * hit
        p.eye, p.mouth = "squeeze", "wavy"
        p.ear = -1.0
        p.head_dx = math.sin(k * 40.0) * 1.2 * (1 - k)
        p.marks = frozenset({"sweat"})

    def _react_startle(self, p, k, data):
        up = math.sin(k * math.pi)
        p.lift = up * 9.0
        p.squash = -0.25 * up
        p.eye, p.mouth = "wide", "o"
        p.arm_l = p.arm_r = 0.35 + up * 1.5
        p.ear = 1.0

    def _react_love(self, p, k, data):
        p.eye = "heart" if self.profile.personality in ("playful", "shy") else "happy"
        p.mouth = "grin"
        p.blush = 1.0
        p.lean = math.sin(k * math.pi * 4) * 0.07
        p.head_tilt = math.sin(k * math.pi * 4) * 0.06
        p.bob = math.sin(self.t * 38.0) * 0.35
        p.ear = 0.6

    def _react_sheepish(self, p, k, data):
        p.eye, p.mouth, p.brow = "closed", "wavy", "sad"
        p.arm_r = 2.3 + math.sin(k * math.pi * 5) * 0.12
        p.head_tilt = 0.1
        p.marks = frozenset({"sweat"})
        p.blush = 0.9
        p.ear = -0.7

    def _react_dizzy(self, p, k, data):
        p.eye, p.mouth = "spiral", "wavy"
        p.marks = frozenset({"dizzy"})
        p.lean = math.sin(k * math.pi * 5) * 0.09 * (1 - k)
        p.sit = 0.6
        p.ear = -0.6

    def _react_sig(self, p, k, data):
        self.trait.react(self, p, data.get("name", ""), k, data)

    def _react_zapped(self, p, k, data):
        p.shock = True
        p.flash = 0.9 if int(k * 12) % 2 == 0 else 0.1
        p.eye, p.mouth = "wide", "teeth"
        p.head_dx = math.sin(self.t * 60.0) * 1.3
        p.arm_l = p.arm_r = 1.6
        if not data.get("fx"):
            data["fx"] = True
            self.fx.bolts(3, 0, -44, 38)

    def _react_munch(self, p, k, data):
        chew = math.sin(k * math.pi * 14)
        p.eye, p.mouth = "happy", "grin"
        p.mouth_open = 0.5 + 0.5 * chew
        p.arm_l = p.arm_r = 1.2
        p.arm_fwd_l = p.arm_fwd_r = 0.6
        p.blush = 0.9
        if not data.get("fx") and k > 0.75:
            data["fx"] = True
            self.fx.hearts(2)

    # -- locomotion + micro-motion -----------------------------------------

    def _walk(self, p, dt, target, speed):
        w = self.world
        dx = target - self.x
        if abs(dx) < 1.5:
            return True
        direction = 1.0 if dx > 0 else -1.0
        step = speed * w.scale * dt
        if step >= abs(dx):
            self.x = target
        else:
            self.x += direction * step
        self.moving = True
        self.face_to = direction
        self.walk_phase += step / (w.scale * 5.2)
        ph = self.walk_phase
        fast = speed > WALK_SPEED * 1.6
        stride, lift = (4.2, 4.4) if fast else (3.0, 3.2)
        p.foot_l = (math.cos(ph) * stride * direction, -max(0.0, math.sin(ph)) * lift)
        p.foot_r = (math.cos(ph + math.pi) * stride * direction, -max(0.0, math.sin(ph + math.pi)) * lift)
        p.bob = -abs(math.sin(ph)) * (2.2 if fast else 1.3)
        p.lean = direction * (0.1 if fast else 0.045)
        p.arm_l = 0.35 + math.sin(ph) * 0.4
        p.arm_r = 0.35 - math.sin(ph) * 0.4
        p.ear = 0.3
        return abs(target - self.x) < 1.5

    def _micro(self, p, dt):
        # facing
        self.facing += (clamp(self.face_to, -1, 1) - self.facing) * min(1.0, dt * 9.0)
        p.facing = self.facing
        if self.facing > 0.2:
            want = -1.0
        elif self.facing < -0.2:
            want = 1.0
        else:
            want = -1.0 if self.tail_side <= 0 else 1.0
        self.tail_side += (want - self.tail_side) * min(1.0, dt * 8.0)
        p.tail_side = self.tail_side
        if not self.moving and self.mode == "idle" and self.idle in ("stand", "sit", "hum", "sleep", "yawn"):
            self.face_to *= max(0.0, 1 - dt * 0.8)
        # breathing + tail
        s = self.session
        if self.asleep and self.idle == "sleep":
            angle = self.sleep_step * math.tau / SLEEP_FRAMES
            p.breath = math.sin(angle)
            p.tail = math.sin(angle) * 0.25
            if p.lie >= 1.0 and not p.marks and abs(self.facing) < 0.02:
                p.cache_key = ("sleep", self.sleep_step, round(self.tail_side, 1))
        else:
            p.breath = math.sin(self.t * 2.1)
            lively = 0.6 + s.mood * 0.9 if s is not None else 1.0
            if not p.held:
                wag = 7.0 if (p.eye in ("happy", "sparkle", "heart") and SPECIES.get(self.design.species, {}).get("tail") == "dog") else 1.7
                p.tail = math.sin(self.t * wag * lively) * 0.7
        # blinking
        if p.eye in ("open", "sleepy", "sad", "angry") and not self.asleep:
            if self.blink_t >= 0:
                self.blink_t += dt
                p.eye_open = min(p.eye_open, abs(self.blink_t - 0.07) / 0.07)
                if self.blink_t >= 0.14:
                    self.blink_t = -1.0
                    self.blink_in = self.rng.uniform(0.25, 0.4) if self.rng.random() < 0.15 else self.rng.uniform(2.0, 6.0)
            else:
                self.blink_in -= dt
                if self.blink_in <= 0:
                    self.blink_t = 0.0
        # the pointer is nearby: look at it
        if self.hover and self.pointer and p.look == (0.0, 0.0) and not self.asleep:
            px, py = self.pointer
            p.look = (clamp(px / 30.0, -1, 1), clamp((py + 48) / 30.0, -1, 1))
            p.ear = max(p.ear, 0.6)

    # ------------------------------------------------------------------
    # status card
    # ------------------------------------------------------------------

    def status_line(self, now):
        s = self.session
        if s is None:
            return "No session"
        if self.leaving or s.ended:
            return "Saying goodbye"
        if s.needs_user and s.needs_reason != "idle":
            waited = fmt_duration(now - s.needs_since) if s.needs_since else ""
            what = {"question": "Has a question for you", "elicitation": "Needs your input"}.get(
                s.needs_reason, "Needs your permission")
            return "%s%s" % (what, " · %s" % waited if waited else "")
        if s.activity in A.WORKING:
            base = s.detail or s.activity.capitalize()
            if s.subagents:
                base += " · %d helper%s" % (s.subagents, "" if s.subagents == 1 else "s")
            return base
        if s.activity == A.DONE:
            return "Just finished" + (" · %s" % fmt_duration(s.last_turn_duration) if s.last_turn_duration else "")
        if s.activity == A.FAILED:
            return "Hit an API error"
        idle_for = now - s.activity_since if s.activity_since else 0
        if self.asleep:
            return "Napping · idle %s" % fmt_duration(idle_for)
        return "Waiting for your next prompt" + (" · %s" % fmt_duration(idle_for) if idle_for > 60 else "")

    def card_info(self, now):
        s = self.session
        prof = self.profile
        species = SPECIES.get(self.design.species, {}).get("label", "Pet")
        subtitle = "%s · %s" % (species, prof.project)
        if s is not None and s.name and s.name != prof.project:
            subtitle += " · %s" % s.name
        info = {
            "name": prof.name, "badge": "Lv %d" % prof.level, "subtitle": subtitle,
            "status": self.status_line(now), "feeling": "", "energy": 1.0, "mood": 0.6, "focus": 0.0,
            "context": None, "footer": "",
        }
        if s is None:
            return info
        feeling = FEELING.get(s.emotion, "feeling fine")
        if self.cfg("show_prompt", True) and s.last_prompt:
            feeling = "%s — “%s”" % (feeling, s.last_prompt)
        info.update(feeling=feeling, energy=s.energy, mood=s.mood, focus=s.focus, context=s.context_pct)
        bits = ["%d tool%s" % (s.tools_ok + s.tools_failed, "" if s.tools_ok + s.tools_failed == 1 else "s")]
        if s.tools_failed:
            bits.append("%d failed" % s.tools_failed)
        if s.edits:
            bits.append("%d edit%s" % (s.edits, "" if s.edits == 1 else "s"))
        if s.started_at:
            bits.append("up %s" % fmt_duration(now - s.started_at))
        bits.append("♥ %d" % int(prof.stats.get("pets", 0)))
        info["footer"] = " · ".join(bits)
        return info
