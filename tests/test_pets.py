"""Tests for the desktop half that needs no display: profiles, design edits,
config, the pet brain and the off-screen renderer."""

import json
import os
import random
import tempfile
import unittest

from claude_pets import config as config_mod
from claude_pets.brain import Pet, World, fmt_duration
from claude_pets.model import Activity as A
from claude_pets.model import Emotion as E
from claude_pets.model import SessionState
from claude_pets.model import Signal as S
from claude_pets.render.creature import ACCESSORIES, COATS, SPECIES, SPECIES_ORDER, Design
from claude_pets.store import PERSONALITIES, Store, apply_changes, level_for, pet_key, xp_for

CFG = dict(config_mod.DEFAULTS)


def make_pet(store, cwd="/work/demo", entrance="pop", now=1000.0, cfg=None, world=None):
    world = world or World(0, 32, 1920, 1194, 1.0, dict(cfg or CFG), random.Random(3))
    profile = store.get(cwd, len([p for p in world.pets if p.profile.cwd == cwd]) + 1)
    pet = Pet("sid-%d" % len(world.pets), profile, world, now, entrance=entrance)
    world.pets.append(pet)
    world.now = now
    return pet


def run(pet, seconds, now, dt=1 / 30):
    for _ in range(int(seconds / dt)):
        now += dt
        pet.world.now = now
        for other in pet.world.pets:
            other.update(dt, now)
    return now


def state(activity, emotion=E.CONTENT, now=1000.0, **kw):
    s = SessionState(session_id="x", cwd="/work/demo", project="demo", activity=activity,
                     activity_since=now, started_at=now - 300, emotion=emotion)
    for key, value in kw.items():
        setattr(s, key, value)
    return s


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_project_same_pet(self):
        a = self.store.get("/home/me/project")
        b = Store(self.tmp.name).get("/home/me/project/")
        self.assertEqual(a.key, b.key)
        self.assertEqual((a.name, a.design), (b.name, b.design))
        self.assertIn(a.design.species, SPECIES)

    def test_second_session_gets_a_sibling(self):
        a = self.store.get("/home/me/project", 1)
        b = self.store.get("/home/me/project", 2)
        self.assertNotEqual(a.key, b.key)
        self.assertEqual(b.project, "project #2")

    def test_headless_profiles_are_not_written(self):
        self.store.get("/tmp/scratch", persistent=False)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_changes_roundtrip_and_validation(self):
        prof = self.store.get("/home/me/project")
        changed, errors = apply_changes(prof, {
            "species": "dragon", "fur": "#8B5CF6", "accessory": "crown", "name": "Ember",
            "pattern": "tabby", "personality": "nope", "eye": "red",
        })
        self.assertEqual(prof.design.species, "dragon")
        self.assertEqual(prof.design.fur, "#8B5CF6")
        self.assertEqual(prof.design.accessory, "crown")
        self.assertEqual(prof.name, "Ember")
        self.assertEqual(prof.design.pattern, "plain")       # dragons have no tabby
        self.assertEqual(len(errors), 3)
        self.assertIn("species", changed)
        self.store.save(prof)
        again = self.store.load_key(prof.key)
        self.assertEqual(again.design, prof.design)
        self.assertEqual(again.name, "Ember")

    def test_species_change_takes_default_coat(self):
        prof = self.store.get("/home/me/project")
        apply_changes(prof, {"species": "penguin"})
        self.assertEqual((prof.design.fur, prof.design.belly, prof.design.extra), COATS["penguin"][0])

    def test_random_design_is_always_valid(self):
        prof = self.store.get("/home/me/project")
        rng = random.Random(1)
        for _ in range(60):
            apply_changes(prof, {"random": True}, rng=rng)
            d = prof.design
            self.assertIn(d.pattern, SPECIES[d.species]["patterns"])
            self.assertIn(d.accessory, ACCESSORIES)

    def test_corrupt_profile_falls_back(self):
        key = pet_key("/home/me/project")
        with open(os.path.join(self.tmp.name, key + ".json"), "w") as fh:
            json.dump({"cwd": "/home/me/project", "name": "", "design": {"species": "unicorn", "fur": "zzz"},
                       "stats": {"xp": "lots"}}, fh)
        prof = self.store.load_key(key)
        self.assertIn(prof.design.species, SPECIES)
        self.assertTrue(prof.name)
        self.assertEqual(prof.xp, 0)

    def test_find(self):
        prof = self.store.get("/home/me/project")
        apply_changes(prof, {"name": "Rune"})
        self.store.save(prof)
        for query in ("Rune", "rune", prof.key, "project", "/home/me/project"):
            self.assertEqual(self.store.find(query).key, prof.key, query)
        self.assertIsNone(self.store.find("nobody"))

    def test_levels(self):
        self.assertEqual(level_for(0), 1)
        for level in range(1, 12):
            self.assertEqual(level_for(xp_for(level)), level)
        prof = self.store.get("/home/me/project")
        self.assertEqual(prof.add_xp(xp_for(2)), 2)
        self.assertEqual(prof.add_xp(1), 0)

    def test_every_species_has_coats_and_plain(self):
        for name in SPECIES_ORDER:
            self.assertIn("plain", SPECIES[name]["patterns"])
            self.assertTrue(COATS[name])
        self.assertTrue(PERSONALITIES)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_bad_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            self.assertEqual(config_mod.load(path), config_mod.DEFAULTS)
            with open(path, "w") as fh:
                json.dump({"scale": 9, "bubbles": "loud", "wander": "yes", "unknown": 1}, fh)
            cfg = config_mod.load(path)
            self.assertEqual(cfg["scale"], 2.0)
            self.assertEqual(cfg["bubbles"], "all")
            self.assertIs(cfg["wander"], True)
            self.assertNotIn("unknown", cfg)
            self.assertEqual(config_mod.set_value("scale", "1.5", path), 1.5)
            self.assertIs(config_mod.set_value("gravity", "off", path), False)
            with self.assertRaises(KeyError):
                config_mod.set_value("nope", "1", path)


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_modes_follow_the_session(self):
        pet = make_pet(self.store)
        now = run(pet, 2.5, 1000.0)
        self.assertEqual(pet.phase, "live")
        pet.on_session(state(A.WRITING, now=now, detail="Editing a.py"), [(S.TOOL_START, {"detail": "Editing a.py"})])
        now = run(pet, 1.0, now)
        self.assertEqual((pet.mode, pet.pose.prop), ("work", "laptop"))
        self.assertIn("Editing a.py", pet.bubble["text"])
        pet.on_session(state(A.WAITING, now=now, needs_user=True, needs_reason="permission", needs_since=now,
                             needs_detail="Bash: rm -rf x"), [(S.NEEDS_USER, {"reason": "permission"})])
        now = run(pet, 1.0, now)
        self.assertEqual((pet.mode, pet.pose.prop, pet.pose.prop_text), ("alert", "sign", "!"))
        self.assertTrue(pet.bubble["sticky"])
        pet.on_session(state(A.THINKING, now=now), [(S.USER_RESPONDED, {})])
        now = run(pet, 1.0, now)
        self.assertEqual(pet.mode, "work")
        self.assertFalse(pet.bubble and pet.bubble["sticky"])
        pet.on_session(state(A.DONE, E.JOYFUL, now=now), [(S.TURN_DONE, {"duration": 90, "tools": 8, "errors": 0})])
        now = run(pet, 0.3, now)
        self.assertEqual(pet.pose.hat, "party")
        now = run(pet, 2.5, now)
        self.assertEqual((pet.mode, pet.pose.prop), ("done", "flag"))
        self.assertGreater(pet.profile.xp, 0)

    def test_every_activity_and_emotion_poses_without_error(self):
        pet = make_pet(self.store)
        now = run(pet, 2.5, 1000.0)
        for activity in A.ALL:
            for emotion in E.ALL:
                pet.on_session(state(activity, emotion, now=now, needs_user=activity in A.NEEDS_USER,
                                     needs_reason="question" if activity == A.ASKING else "permission",
                                     needs_since=now, subagents=2, context_pct=0.95, mood=0.05), [])
                now = run(pet, 0.2, now)
                if activity == A.ENDED:
                    break
        self.assertTrue(pet.leaving or pet.mode)

    def test_every_signal_is_handled(self):
        pet = make_pet(self.store)
        now = run(pet, 2.5, 1000.0)
        for name in S.ALL:
            if name == S.SESSION_END:
                continue
            pet.on_session(state(A.THINKING, now=now), [(name, {})])
            now = run(pet, 0.4, now)
        pet.on_session(state(A.THINKING, now=now), [(S.SESSION_END, {"reason": "other"})])
        now = run(pet, 3.0, now)
        self.assertTrue(pet.gone)

    def test_sleeps_when_idle_long_and_wakes_on_work(self):
        pet = make_pet(self.store)
        now = run(pet, 2.5, 1000.0)
        pet.on_session(state(A.IDLE, E.SLEEPY, now=now - 900), [])
        now = run(pet, 12.0, now)
        self.assertTrue(pet.asleep)
        self.assertEqual(pet.pose.hat, "nightcap")
        self.assertLessEqual(pet.desired_fps(), 6)
        pet.on_session(state(A.THINKING, now=now), [(S.PROMPT, {"sentiment": "neutral"})])
        now = run(pet, 1.5, now)
        self.assertFalse(pet.asleep)
        self.assertEqual(pet.mode, "work")

    def test_drag_drop_falls_to_the_floor_and_remembers_home(self):
        pet = make_pet(self.store)
        now = run(pet, 2.5, 1000.0)
        pet.grab(600, 400)
        pet.drag_to(640, 380)
        now = run(pet, 0.6, now)
        self.assertTrue(pet.pose.held)
        self.assertLess(pet.y, pet.world.floor)
        pet.release(300, -200)
        for _ in range(300):                     # until it has landed (before it wanders off again)
            now = run(pet, 1 / 30, now)
            if not pet.airborne:
                break
        self.assertFalse(pet.airborne)
        self.assertEqual(pet.y, pet.world.floor)
        self.assertAlmostEqual(pet.home_x, pet.x)
        self.assertAlmostEqual(pet.profile.home, pet.x / 1920.0, places=3)

    def test_no_gravity_keeps_the_perch(self):
        pet = make_pet(self.store, cfg=dict(CFG, gravity=False))
        now = run(pet, 2.5, 1000.0)
        pet.grab(500, 300)
        now = run(pet, 0.5, now)
        pet.release(0, 0)
        now = run(pet, 1.0, now)
        self.assertLess(pet.y, pet.world.floor - 100)
        self.assertGreaterEqual(pet.profile.perch, 0)

    def test_pets_take_separate_homes_and_stay_on_screen(self):
        world = World(0, 32, 1920, 1194, 1.0, dict(CFG), random.Random(5))
        pets = [make_pet(self.store, "/work/p%d" % i, world=world) for i in range(8)]
        homes = sorted(p.home_x for p in pets)
        self.assertTrue(all(b - a > 60 for a, b in zip(homes, homes[1:])))
        now = 1000.0
        for pet in pets:
            pet.on_session(state(A.IDLE, E.HAPPY, now=now), [])
        now = run(pets[0], 60.0, now)
        for pet in pets:
            self.assertGreaterEqual(pet.x, world.left)
            self.assertLessEqual(pet.x, world.right)

    def test_walks_in_for_new_sessions(self):
        pet = make_pet(self.store, entrance="walk")
        self.assertEqual(pet.phase, "enter")
        self.assertTrue(pet.x > pet.world.right or pet.x < pet.world.left)
        now = 1000.0
        for _ in range(600):                     # it runs in from the screen edge to its spot
            now = run(pet, 1 / 30, now)
            if pet.phase == "live":
                break
        self.assertEqual(pet.phase, "live")
        self.assertAlmostEqual(pet.x, pet.home_x, delta=2)
        self.assertIn("Hi!", pet.bubble["text"])

    def test_card_info(self):
        pet = make_pet(self.store)
        now = run(pet, 2.5, 1000.0)
        pet.on_session(state(A.READING, E.CURIOUS, now=now, detail="Reading x.py", context_pct=0.42,
                             last_prompt="fix the bug", tools_ok=3, name="demo-1a"), [])
        info = pet.card_info(now)
        self.assertEqual(info["status"], "Reading x.py")
        self.assertIn("curious", info["feeling"])
        self.assertIn("fix the bug", info["feeling"])
        self.assertEqual(info["context"], 0.42)
        self.assertIn("3 tools", info["footer"])

    def test_bubble_modes(self):
        pet = make_pet(self.store, cfg=dict(CFG, bubbles="important"))
        pet.say("chatter")
        self.assertIsNone(pet.bubble)
        pet.say("urgent", important=True)
        self.assertIsNotNone(pet.bubble)
        quiet = make_pet(self.store, "/work/quiet", cfg=dict(CFG, bubbles="off"))
        quiet.say("urgent", important=True)
        self.assertIsNone(quiet.bubble)

    def test_fmt_duration(self):
        self.assertEqual(fmt_duration(5), "5s")
        self.assertEqual(fmt_duration(134), "2m 14s")
        self.assertEqual(fmt_duration(3725), "1h 02m")


class RenderTests(unittest.TestCase):
    """The renderer must cope with every design and pose (drawn off-screen)."""

    def test_all_species_poses_and_scene(self):
        import cairo

        from claude_pets.render import scene
        from claude_pets.render.creature import PATTERNS, Pose, default_design, draw_pet
        from claude_pets.render.tokens import Theme

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
        cr = cairo.Context(surface)
        eyes = ("open", "happy", "closed", "wide", "sparkle", "heart", "spiral", "x", "squeeze", "sleepy")
        mouths = ("smile", "cat", "grin", "o", "flat", "frown", "wavy", "tongue", "teeth", "yawn", "none")
        props = ("", "laptop", "book", "magnifier", "clipboard", "mug", "sign", "flag", "terminal", "globe", "gear")
        hats = ("", "party", "hardhat", "nightcap", "headphones")
        marks = frozenset({"sweat", "tear", "anger", "gloom", "bandage", "thermo", "cloud", "dizzy"})
        for i, species in enumerate(SPECIES_ORDER):
            for j, accessory in enumerate(ACCESSORIES):
                design = default_design(species, j, j)
                design.accessory = accessory
                design.pattern = PATTERNS[(i + j) % len(PATTERNS)]
                pose = Pose(t=j * 0.37, eye=eyes[j % len(eyes)], mouth=mouths[j % len(mouths)],
                            prop=props[(i + j) % len(props)], hat=hats[j % len(hats)], marks=marks,
                            facing=(-1, 0, 1)[j % 3], sit=j % 2, lie=(j % 3) / 2.0, lift=j, squash=0.3,
                            held=j % 5 == 0, dangle=0.3, glasses=j % 2 == 0, belly=0.8, brow="angry")
                cr.save()
                cr.translate(100, 180)
                draw_pet(cr, design, pose, rim=((1, 1, 1), 1.7))
                cr.restore()
        surface.flush()                       # pycairo raises if the surface went into an error state

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            pet = make_pet(store)
            now = run(pet, 2.5, 1000.0)
            pet.on_session(state(A.DELEGATING, E.HAPPY, now=now, subagents=3, detail="Delegating"),
                           [(S.TOOL_START, {"detail": "Delegating"}), (S.SUBAGENT_START, {"count": 3})])
            now = run(pet, 1.0, now)
            w, h = scene.window_size(1.0)
            canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            ctx = cairo.Context(canvas)
            for scheme in ("dark", "light"):
                scene.draw_scene(ctx, pet, w, h, Theme(scheme), CFG, now)
            box = scene.scene_extents(pet, w, h)
            self.assertTrue(0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h)
            # something was actually painted inside the reported extents
            data = canvas.get_data()
            stride = canvas.get_stride()
            cx, cy = w // 2, h - 70
            self.assertNotEqual(bytes(data[cy * stride + cx * 4: cy * stride + cx * 4 + 4]), b"\x00\x00\x00\x00")

    def test_tokens_resolve(self):
        from claude_pets.render.tokens import COMPONENT, Theme, as_json, gtk_css

        for scheme in ("dark", "light"):
            theme = Theme(scheme)
            for name in COMPONENT:
                self.assertTrue(theme.hex(name).startswith("#"), name)
            self.assertIn(".cp-primary", gtk_css(scheme))
        self.assertEqual(set(as_json()), {"primitive", "semantic", "component"})


class DemoTests(unittest.TestCase):
    def test_demo_drives_the_tracker(self):
        from claude_pets.demo import Demo
        from claude_pets.tracker import SessionTracker

        clock = [5000.0]
        tracker = SessionTracker(clock=lambda: clock[0])
        seen = []
        tracker.subscribe(lambda st, sigs: seen.extend(name for name, _ in sigs))
        demo = Demo(tracker)
        demo.start(3, clock[0])
        for _ in range(150):
            clock[0] += 1.0
            demo.step(clock[0])
            tracker.tick(clock[0])
        self.assertEqual(len(tracker.all()), 3)
        for expected in (S.SESSION_START, S.PROMPT, S.TOOL_START, S.TOOL_OK, S.TOOL_ERROR, S.NEEDS_USER,
                         S.TURN_DONE, S.SUBAGENT_START, S.TESTS_PASSED):
            self.assertIn(expected, seen)
        demo.stop()
        tracker.tick(clock[0] + 1)
        self.assertEqual(tracker.all(), [])


if __name__ == "__main__":
    unittest.main()
