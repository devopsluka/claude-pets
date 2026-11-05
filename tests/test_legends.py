"""Legends: human characters whose signature move replaces petting."""

import os
import random
import tempfile
import unittest

from claude_pets import config as config_mod
from claude_pets.brain import Pet, World
from claude_pets.legends import TRAITS, trait_for
from claude_pets.model import Activity as A
from claude_pets.model import Emotion as E
from claude_pets.model import SessionState
from claude_pets.model import Signal as S
from claude_pets.render.creature import (ALL_SPECIES, COATS, LEGEND_NAMES, LEGENDS, SIGNATURE_ACCENT, SPECIES,
                                         SPECIES_ORDER, Pose, default_design, draw_pet)
from claude_pets.store import NAMES, Store, apply_changes

CFG = dict(config_mod.DEFAULTS)
MOVES = {"tyson": "punch", "snoop": "toke", "pablo": "line", "einstein": "eureka", "tesla": "lightning",
         "arnold": "flex", "trump": "thumbs", "melania": "brush_off", "miku": "leek", "freddie": "ayo",
         "dolly": "wink"}


def state(activity, emotion=E.CONTENT, now=1000.0, **kw):
    s = SessionState(session_id="x", cwd="/work/demo", project="demo", activity=activity,
                     activity_since=now, started_at=now - 300, emotion=emotion)
    for key, value in kw.items():
        setattr(s, key, value)
    return s


class LegendCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.world = World(0, 32, 1920, 1194, 1.0, dict(CFG), random.Random(4))
        self.now = 1000.0

    def tearDown(self):
        self.tmp.cleanup()

    def pet(self, species, x=None):
        profile = self.store.fresh("/work/%s-%d" % (species, len(self.world.pets)))
        profile.persistent = False
        apply_changes(profile, {"species": species})
        pet = Pet("sid-%s-%d" % (species, len(self.world.pets)), profile, self.world, self.now)
        if x is not None:
            pet.x = pet.home_x = x
        self.world.pets.append(pet)
        self.run_for(2.2)
        pet.on_session(state(A.IDLE, E.CONTENT, self.now), [])
        pet.idle, pet.idle_t, pet.idle_dur = "stand", 0.0, 60.0
        return pet

    def run_for(self, seconds, dt=1 / 30):
        for _ in range(int(seconds / dt)):
            self.now += dt
            self.world.now = self.now
            for pet in self.world.pets:
                pet.update(dt, self.now)


class LooksTests(unittest.TestCase):
    def test_every_legend_is_a_complete_character(self):
        self.assertEqual(set(LEGENDS), set(TRAITS) & set(LEGEND_NAMES) & set(SIGNATURE_ACCENT))
        for name in LEGENDS:
            spec = SPECIES[name]
            self.assertTrue(spec["human"] and spec["label"] and COATS[name])
            self.assertTrue(trait_for(name).legend)
            self.assertNotIn(name, SPECIES_ORDER)
            self.assertEqual(default_design(name).accent, SIGNATURE_ACCENT[name])
        self.assertFalse(trait_for("cat").legend)
        self.assertEqual(len(ALL_SPECIES), len(SPECIES_ORDER) + len(LEGENDS))

    def test_legends_draw_in_every_pose(self):
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 220, 220)
        cr = cairo.Context(surface)
        variants = [
            dict(), dict(facing=1.0, look=(1, 0)), dict(sit=1.0, prop="laptop", item="joint", item_at="mouth"),
            dict(hand_r=(40, -26), hand_l=(-9, -33), lean=0.15), dict(prop="mirror", prop_t=0.5, head_dy=15),
            dict(item="bulb", item_at="over", item_glow=1.0, arm_r=2.75), dict(prop="coil", prop_t=0.4),
            dict(prop="chalkboard", prop_side=-1.0, hand_l=(-31, -46)), dict(shock=True, flash=0.9),
            dict(prop="belt", arm_l=2.5, arm_r=2.5), dict(item="bills"), dict(item="pigeon", item_at="over"),
            dict(lie=1.0, eye="closed", hat="nightcap"), dict(held=True, dangle=0.3), dict(hat="party", lift=12),
            dict(prop="sign", arm_r=2.25), dict(prop="book", glasses=True), dict(hat="hardhat"),
        ]
        eyes = ("open", "happy", "closed", "wide", "sparkle", "heart", "spiral", "x", "squeeze", "sleepy")
        mouths = ("smile", "grin", "o", "flat", "frown", "wavy", "tongue", "teeth", "yawn")
        for name in LEGENDS:
            for coat in range(len(COATS[name])):
                for i, kw in enumerate(variants):
                    params = dict(t=i * 0.31, eye=eyes[i % len(eyes)], mouth=mouths[i % len(mouths)],
                                  brow=("", "angry", "sad")[i % 3])
                    params.update(kw)
                    pose = Pose(**params)
                    design = default_design(name, coat)
                    design.accessory = ("none", "crown", "glasses", "scarf", "headphones")[i % 5]
                    cr.save()
                    cr.translate(110, 190)
                    draw_pet(cr, design, pose, rim=((1, 1, 1), 1.7))
                    cr.restore()
        surface.flush()


class IdentityTests(unittest.TestCase):
    def test_casts_decide_who_hatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(40):
                cwd = "/work/project-%d" % i
                legend = Store(tmp, cast="legends").fresh(cwd)
                animal = Store(tmp, cast="animals").fresh(cwd)
                anyone = Store(tmp, cast="mixed").fresh(cwd)
                self.assertIn(legend.design.species, LEGENDS)
                self.assertEqual(legend.name, LEGEND_NAMES[legend.design.species])
                self.assertEqual(legend.design.accessory, "none")
                self.assertIn(animal.design.species, SPECIES_ORDER)
                self.assertIn(animal.name, NAMES)
                self.assertIn(anyone.design.species, ALL_SPECIES)
            self.assertEqual(Store(tmp, cast="nonsense").cast, "animals")

    def test_becoming_a_legend_renames_unless_named_by_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            auto = store.get("/work/a")
            changed, errors = apply_changes(auto, {"species": "tyson"})
            self.assertEqual(errors, [])
            self.assertEqual((auto.name, auto.design.accent), ("Mike", SIGNATURE_ACCENT["tyson"]))
            self.assertEqual((auto.design.fur, auto.design.belly, auto.design.extra), COATS["tyson"][0])
            apply_changes(auto, {"species": "snoop"})
            self.assertEqual(auto.name, "Snoop")
            apply_changes(auto, {"species": "cat"})
            self.assertIn(auto.name, NAMES)
            mine = store.get("/work/b")
            apply_changes(mine, {"name": "Chairman Meow"})
            apply_changes(mine, {"species": "tesla"})
            self.assertEqual(mine.name, "Chairman Meow")
            store.save(auto)
            self.assertEqual(store.load_key(auto.key).design.species, "cat")


class SignatureTests(LegendCase):
    def test_poking_a_legend_does_its_move_not_hearts(self):
        for name in LEGENDS:
            pet = self.pet(name, x=300 + 300 * LEGENDS.index(name))
            before = pet.profile.stats.get("pets", 0)
            self.assertTrue(pet.petted(self.now))
            self.assertEqual(pet.react[0], "sig", name)
            self.assertEqual(pet.react[3]["name"], MOVES[name], name)
            self.assertFalse(any(p.kind == "heart" for p in pet.fx.items), name)
            self.assertEqual(pet.profile.stats["pets"], before + 1)
            self.run_for(4.0)
            self.assertIsNone(pet.react, name)
        cat = self.pet("cat", x=1800)
        cat.petted(self.now)
        self.assertEqual(cat.react[0], "love")
        self.assertTrue(any(p.kind == "heart" for p in cat.fx.items))

    def test_mike_punches_whoever_stands_next_to_him(self):
        mike = self.pet("tyson", x=900)
        bunny = self.pet("bunny", x=970)
        bunny.on_session(state(A.IDLE, E.HAPPY, self.now), [])
        mike.petted(self.now)
        self.assertIs(mike.react[3]["target"], bunny)
        self.run_for(0.5)
        self.assertEqual(bunny.react[0], "dizzy")
        self.assertGreater(bunny.x, 970)                       # knocked back, away from Mike
        self.assertTrue(any(p.kind == "pow" for p in mike.fx.items))
        self.assertIsNotNone(mike.pose.hand_r)
        self.run_for(3.0)
        self.assertIsNone(bunny.react)                         # and fine again

    def test_tesla_lightning_reaches_the_neighbours(self):
        tesla = self.pet("tesla", x=900)
        frog = self.pet("frog", x=960)
        far = self.pet("bear", x=1500)
        tesla.petted(self.now)
        self.run_for(0.6)
        self.assertEqual(frog.react[0], "zapped")
        self.assertTrue(frog.pose.shock)
        self.assertIsNone(far.react)

    def test_session_events_trigger_the_signature(self):
        mike = self.pet("tyson", x=400)
        mike.on_session(state(A.THINKING, E.FRUSTRATED, self.now), [(S.TOOL_ERROR, {"tool": "Bash", "streak": 3})])
        self.assertEqual(mike.react[3]["name"], "punch")
        self.assertIn("exit code 1", mike.bubble["text"])

        tesla = self.pet("tesla", x=700)
        tesla.on_session(state(A.THINKING, E.STRESSED, self.now), [(S.TOOL_ERROR, {"tool": "Bash", "streak": 1})])
        self.assertEqual(tesla.react[3]["name"], "zap")
        self.run_for(0.2)
        self.assertTrue(tesla.pose.shock)
        self.run_for(2.0)
        tesla.on_session(state(A.RUNNING, now=self.now, detail="Building"), [(S.TOOL_START, {"detail": "Building"})])
        self.run_for(1.0)
        self.assertEqual(tesla.pose.prop, "coil")

        pablo = self.pet("pablo", x=1000)
        pablo.on_session(state(A.WAITING, now=self.now, needs_user=True, needs_reason="permission",
                               needs_detail="Bash: make deploy", needs_since=self.now),
                         [(S.NEEDS_USER, {"reason": "permission"})])
        self.assertIn("Plata o plomo?", pablo.bubble["text"])
        self.assertIn("make deploy", pablo.bubble["text"])

        albert = self.pet("einstein", x=1300)
        albert.on_session(state(A.THINKING, now=self.now), [])
        self.run_for(3.2)
        self.assertEqual(albert.pose.prop, "chalkboard")
        albert.on_session(state(A.WRITING, now=self.now, detail="Editing a.py"), [(S.TOOL_START, {"detail": "Editing a.py"})])
        self.assertEqual(albert.react[3]["name"], "eureka")
        self.run_for(0.4)
        self.assertEqual((albert.pose.item, albert.pose.item_at), ("bulb", "over"))

        snoop = self.pet("snoop", x=1600)
        self.run_for(0.2)
        self.assertEqual(snoop.pose.item, "joint")
        snoop.on_session(state(A.DONE, E.JOYFUL, self.now), [(S.TURN_DONE, {"duration": 90, "tools": 8, "errors": 0})])
        self.assertIn("Fo shizzle", snoop.bubble["text"])
        self.assertIn("Done", snoop.bubble["text"])

    def test_melania_brushes_off_donald(self):
        donald = self.pet("trump", x=900)
        melania = self.pet("melania", x=990)
        self.assertTrue(donald.trait.visit(donald, melania))
        self.assertEqual(donald.react[3]["name"], "reach")
        self.assertEqual(melania.react[3]["name"], "brush_off")
        self.assertEqual(donald.react[3]["dir"], -melania.react[3]["dir"])   # he reaches, she turns away
        self.run_for(2.5)
        self.assertIsNone(donald.react)
        self.assertIsNone(melania.react)
        self.assertTrue(melania.trait.visit(melania, donald))
        self.assertEqual(melania.react[3]["name"], "brush_off")

    def test_poking_melania_twice_gets_the_side_eye(self):
        melania = self.pet("melania", x=900)
        melania.petted(self.now)
        self.assertEqual(melania.react[3]["name"], "brush_off")
        self.run_for(2.2)
        melania.petted(self.now)
        self.assertEqual(melania.react[3]["name"], "side_eye")
        self.run_for(8.0)
        melania.petted(self.now)
        self.assertEqual(melania.react[3]["name"], "brush_off")             # she has forgotten you again

    def test_new_legends_react_to_the_session(self):
        expected = {"arnold": "flex", "trump": "thumbs", "melania": "clap", "miku": "sing", "freddie": "champion",
                    "dolly": "wink"}
        for i, (name, move) in enumerate(expected.items()):
            pet = self.pet(name, x=200 + 250 * i)
            pet.on_session(state(A.TESTING, now=self.now), [(S.TESTS_PASSED, {"detail": "ok"})])
            self.assertEqual(pet.react[3]["name"], move, name)
            self.run_for(3.0)
        arnold = self.pet("arnold", x=1700)
        arnold.on_session(state(A.RUNNING, now=self.now, detail="Building"), [(S.TOOL_START, {"detail": "Building"})])
        self.run_for(1.0)
        self.assertEqual(arnold.pose.item, "dumbbell")
        arnold.on_session(state(A.THINKING, E.FRUSTRATED, self.now), [(S.TOOL_ERROR, {"tool": "Bash", "streak": 3})])
        self.assertIn("choppa", arnold.bubble["text"])
        freddie = self.pet("freddie", x=1850)
        self.run_for(0.2)
        self.assertEqual(freddie.pose.item, "mic")

    def test_legends_survive_every_state_and_signal(self):
        from claude_pets.render import scene
        from claude_pets.render.tokens import Theme
        import cairo

        w, h = scene.window_size(1.0)
        ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h))
        theme = Theme("dark")
        for name in LEGENDS:
            pet = self.pet(name, x=960)
            for activity in A.ALL:
                if activity == A.ENDED:
                    continue
                for emotion in (E.CONTENT, E.JOYFUL, E.TIRED, E.SLEEPY, E.FRUSTRATED, E.SAD, E.ANXIOUS, E.SICK, E.STUFFED):
                    pet.on_session(state(activity, emotion, self.now, needs_user=activity in A.NEEDS_USER,
                                         needs_reason="permission", needs_since=self.now - 60, subagents=1,
                                         context_pct=0.92, energy=0.2), [])
                    self.run_for(0.25)
                    scene.draw_scene(ctx, pet, w, h, theme, CFG, self.now)
                    box = scene.scene_extents(pet, w, h)
                    self.assertTrue(box[0] < box[2] and box[1] < box[3])
            for signal in S.ALL:
                if signal != S.SESSION_END:
                    pet.on_session(state(A.THINKING, now=self.now), [(signal, {})])
                    self.run_for(0.3)
                    scene.draw_scene(ctx, pet, w, h, theme, CFG, self.now)
            for idle in list(trait_for(name).idle) + ["sleep"]:
                pet.on_session(state(A.IDLE, now=self.now), [])
                pet.react = None
                pet.idle, pet.idle_t, pet.idle_dur, pet.idle_data = idle, 0.0, 6.0, {}
                self.run_for(3.0)
                scene.draw_scene(ctx, pet, w, h, theme, CFG, self.now)
            self.world.pets.remove(pet)


class VoiceTests(LegendCase):
    def test_snarky_pets_reword_but_keep_the_facts(self):
        from claude_pets import voice

        cat = self.pet("cat", x=400)
        apply_changes(cat.profile, {"personality": "snarky"})
        cat.on_session(state(A.THINKING, now=self.now), [(S.TOOL_ERROR, {"tool": "Bash", "streak": 4})])
        self.assertIn(cat.bubble["plain"], [line.format(n=4) for line in voice.SNARKY["streak_err"]])
        cat.on_session(state(A.TESTING, now=self.now), [(S.TESTS_PASSED, {})])
        self.assertIn(cat.bubble["plain"], voice.SNARKY["tests_passed"])
        cat.on_session(state(A.DONE, now=self.now), [(S.TURN_DONE, {"duration": 90, "tools": 4, "errors": 0})])
        opener, *facts = cat.bubble["plain"].split(" · ")
        self.assertIn(opener, voice.SNARKY["done"])
        self.assertEqual(facts[-1], "4 tools")
        cat.on_session(state(A.WAITING, now=self.now, needs_user=True, needs_reason="permission",
                             needs_detail="Bash: rm -rf build", needs_since=self.now),
                       [(S.NEEDS_USER, {"reason": "permission"})])
        self.assertTrue(cat.bubble["plain"].endswith("Bash: rm -rf build"))     # the request itself stays readable

    def test_ordinary_pets_keep_their_cheer(self):
        dog = self.pet("dog", x=600)
        apply_changes(dog.profile, {"personality": "playful"})
        dog.on_session(state(A.TESTING, now=self.now), [(S.TESTS_PASSED, {})])
        self.assertEqual(dog.bubble["plain"], "Tests passed!")

    def test_melania_comes_snarky_and_nobody_hatches_that_way(self):
        from claude_pets.store import HATCH_PERSONALITIES

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            mine = store.get("/work/m")
            apply_changes(mine, {"personality": "calm"})
            apply_changes(mine, {"species": "melania"})
            self.assertEqual(mine.personality, "snarky")
            nice = store.get("/work/n")
            apply_changes(nice, {"species": "melania", "personality": "shy"})
            self.assertEqual(nice.personality, "shy")                          # asked for explicitly
            self.assertNotIn("snarky", HATCH_PERSONALITIES)
            legends = Store(tmp, cast="legends")
            for i in range(60):
                prof = legends.fresh("/work/p-%d" % i)
                expected = "snarky" if prof.design.species == "melania" else None
                if expected:
                    self.assertEqual(prof.personality, expected)
                else:
                    self.assertIn(prof.personality, HATCH_PERSONALITIES)


class DemoCastTests(unittest.TestCase):
    def test_legends_demo_brings_everyone_and_ends_by_itself(self):
        from claude_pets.demo import Demo
        from claude_pets.tracker import SessionTracker

        clock = [9000.0]
        tracker = SessionTracker(clock=lambda: clock[0])
        demo = Demo(tracker)
        demo.start(0, clock[0], cast="legends", seconds=30)
        for _ in range(20):
            clock[0] += 1.0
            demo.step(clock[0])
            tracker.tick(clock[0])
        self.assertEqual(sorted(os.path.basename(s.cwd) for s in tracker.all()), sorted(LEGENDS))
        self.assertTrue(all(s.entrypoint == "demo" for s in tracker.all()))
        for _ in range(15):
            clock[0] += 1.0
            demo.step(clock[0])
            tracker.tick(clock[0])
        self.assertEqual(tracker.all(), [])


if __name__ == "__main__":
    unittest.main()
