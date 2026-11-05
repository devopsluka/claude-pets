import unittest

import test_support  # noqa: F401  (sys.path)

from claude_pets.model import Activity, Emotion, SessionState, Signal
from claude_pets.mood import MoodEngine

T0 = 1_800_000_000.0


def make(activity=Activity.IDLE, **fields):
    state = SessionState(session_id="s")
    state.activity = activity
    state.activity_since = T0
    for key, value in fields.items():
        setattr(state, key, value)
    return state


class MoodEngineTest(unittest.TestCase):
    def setUp(self):
        self.m = MoodEngine()

    def test_values_stay_in_range(self):
        st = make()
        for _ in range(50):
            self.m.apply(st, Signal.PROMPT, {"sentiment": "praise"}, T0)
            self.m.apply(st, Signal.TOOL_OK, {"streak": 1}, T0)
        self.assertEqual((st.mood, st.stress), (1.0, 0.0))
        for i in range(50):
            self.m.apply(st, Signal.TOOL_ERROR, {"streak": i + 1}, T0)
            self.m.apply(st, Signal.TURN_FAILED, {"error": "overloaded"}, T0)
        self.assertEqual((st.mood, st.stress, st.focus), (0.0, 1.0, 0.0))
        self.m.tick(st, 10 ** 7, T0)
        for value in (st.energy, st.mood, st.stress, st.focus):
            self.assertTrue(0.0 <= value <= 1.0)

    def test_is_deterministic(self):
        def run():
            st = make(Activity.THINKING)
            now = T0
            for i in range(200):
                now += 3
                self.m.tick(st, 3, now)
                self.m.apply(st, Signal.TOOL_ERROR if i % 7 == 0 else Signal.TOOL_OK, {"streak": 1}, now)
            return st.energy, st.mood, st.stress, st.focus, st.emotion
        self.assertEqual(run(), run())

    def test_praise_brings_joy_that_fades(self):
        st = make(Activity.THINKING)
        self.m.apply(st, Signal.PROMPT, {"sentiment": "praise"}, T0)
        self.assertEqual(st.emotion, Emotion.JOYFUL)
        self.assertAlmostEqual(st.mood, 0.85)
        self.m.tick(st, 30, T0 + 30)
        self.assertEqual(st.emotion, Emotion.HAPPY)
        self.m.tick(st, 3600, T0 + 3630)   # an hour later the glow is gone
        self.assertLess(st.mood, 0.65)

    def test_scolding_makes_it_determined_not_sad(self):
        st = make(Activity.THINKING)
        self.m.apply(st, Signal.PROMPT, {"sentiment": "frustrated"}, T0)
        self.assertAlmostEqual(st.mood, 0.42)
        self.m.apply(st, Signal.TOOL_ERROR, {"streak": 1}, T0)
        self.assertEqual(st.emotion, Emotion.DETERMINED)

    def test_error_streak_escalates(self):
        st = make(Activity.RUNNING)
        moods = []
        for streak in (1, 2, 3):
            st.error_streak = streak
            self.m.apply(st, Signal.TOOL_ERROR, {"streak": streak}, T0)
            moods.append(round(st.mood, 3))
        self.assertEqual(moods, [0.54, 0.45, 0.33])
        self.assertEqual(st.emotion, Emotion.FRUSTRATED)
        st.error_streak = 0
        for _ in range(12):
            self.m.apply(st, Signal.TOOL_OK, {"streak": 1}, T0)
        self.assertNotIn(st.emotion, (Emotion.FRUSTRATED, Emotion.STRESSED))

    def test_passing_tests_relieve_stress(self):
        st = make(Activity.TESTING, stress=0.6, mood=0.4)
        self.assertEqual(self.m.emotion(st, T0), Emotion.STRESSED)
        self.m.apply(st, Signal.TESTS_PASSED, {}, T0)
        self.assertEqual(st.emotion, Emotion.JOYFUL)
        self.assertAlmostEqual(st.stress, 0.45)

    def test_focus_builds_during_long_work(self):
        st = make(Activity.WRITING)
        now = T0
        for _ in range(8 * 60):
            now += 1
            self.m.tick(st, 1, now)
        self.assertEqual(st.emotion, Emotion.FOCUSED)
        self.m.apply(st, Signal.INTERRUPTED, {}, now)
        self.assertEqual(st.focus, 0.0)

    def test_marathon_work_is_tiring_and_rest_restores(self):
        st = make(Activity.RUNNING)
        self.m.tick(st, 100 * 60, T0 + 6000)          # 100 minutes flat out
        self.assertLessEqual(st.energy, 0.25)
        self.assertEqual(st.emotion, Emotion.TIRED)
        st.activity = Activity.IDLE
        st.activity_since = T0 + 6000
        self.m.tick(st, 15 * 60, T0 + 6900)
        self.assertEqual(st.energy, 1.0)

    def test_idle_gets_bored_then_sleepy(self):
        st = make(Activity.IDLE)
        self.assertEqual(self.m.emotion(st, T0 + 60), Emotion.CONTENT)
        self.assertEqual(self.m.emotion(st, T0 + 5 * 60), Emotion.BORED)
        self.assertEqual(self.m.emotion(st, T0 + 11 * 60), Emotion.SLEEPY)

    def test_big_clean_turn_makes_it_proud(self):
        st = make(Activity.DONE)
        self.m.apply(st, Signal.TURN_DONE, {"duration": 420, "tools": 23, "errors": 0, "edits": 4}, T0)
        self.assertEqual(st.emotion, Emotion.JOYFUL)
        st.activity = Activity.IDLE
        st.activity_since = T0 + 6
        self.assertEqual(self.m.emotion(st, T0 + 40), Emotion.PROUD)
        self.assertEqual(self.m.emotion(st, T0 + 200), Emotion.HAPPY)

    def test_continued_turn_done_does_not_inflate_mood(self):
        st = make(Activity.DONE)
        before = st.mood
        self.m.apply(st, Signal.TURN_DONE, {"duration": 5, "tools": 1, "errors": 0, "continued": True}, T0)
        self.assertEqual(st.mood, before)

    def test_api_failure_makes_it_sick_for_a_minute(self):
        st = make(Activity.IDLE)
        self.m.apply(st, Signal.TURN_FAILED, {"error": "overloaded"}, T0)
        self.assertEqual(st.emotion, Emotion.SICK)
        self.assertEqual(self.m.emotion(st, T0 + 61), Emotion.CONTENT)
        st.activity = Activity.FAILED
        self.assertEqual(self.m.emotion(st, T0 + 500), Emotion.SICK)

    def test_full_context_is_stuffed_and_stressful(self):
        st = make(Activity.THINKING, context_pct=0.85)
        self.m.tick(st, 1, T0 + 1)
        self.assertAlmostEqual(st.stress, 0.3, places=2)
        st.context_pct = 0.95
        self.m.tick(st, 1, T0 + 2)
        self.assertEqual(st.emotion, Emotion.STUFFED)
        self.assertGreaterEqual(st.stress, 0.5)

    def test_long_wait_for_the_user_is_anxious(self):
        st = make(Activity.WAITING, needs_user=True, needs_reason="permission", needs_since=T0)
        self.assertEqual(self.m.emotion(st, T0 + 60), Emotion.CONTENT)
        self.assertEqual(self.m.emotion(st, T0 + 181), Emotion.ANXIOUS)

    def test_exploring_is_curious(self):
        st = make(Activity.SEARCHING)
        self.assertEqual(self.m.emotion(st, T0), Emotion.CURIOUS)
        st.activity = Activity.WRITING
        self.assertEqual(self.m.emotion(st, T0), Emotion.CONTENT)

    def test_every_emotion_is_a_known_label(self):
        st = make()
        self.assertIn(self.m.emotion(st, T0), Emotion.ALL)


if __name__ == "__main__":
    unittest.main()
