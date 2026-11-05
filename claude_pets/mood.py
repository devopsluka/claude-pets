"""Mood engine: turns session events and the passage of time into feelings.

Four slow-moving numbers live on every :class:`~claude_pets.model.SessionState`
(``energy``, ``mood``, ``stress``, ``focus``, all 0..1).  One-shot signals push
them around (:meth:`MoodEngine.apply`), time pulls them back
(:meth:`MoodEngine.tick`), and :meth:`MoodEngine.emotion` condenses them plus
the session's situation into a single :class:`~claude_pets.model.Emotion`.

The engine is deterministic: same inputs, same feelings.
"""

from __future__ import annotations

import math

from .model import Activity, Emotion, Signal

MOOD_BASELINE = 0.6
MOOD_RELAX_TAU = 20 * 60.0       # mood drifts back to baseline (e-folding time)
ENERGY_DRAIN_PER_S = 0.5 / 3600  # while working
ENERGY_REST_PER_S = 1.0 / 900    # while resting: full in ~15 min
FOCUS_RISE_PER_S = 1.0 / 600     # full after ~10 min of uninterrupted work
FOCUS_DECAY_PER_S = 1.0 / 120
STRESS_DECAY_PER_S = 1.0 / 300

JOY_SECS = 20.0
SICK_SECS = 60.0
PROUD_SECS = 120.0
ANXIOUS_AFTER = 180.0
BORED_AFTER = 4 * 60.0
SLEEPY_AFTER = 10 * 60.0

_EXPLORING = frozenset({Activity.READING, Activity.SEARCHING, Activity.BROWSING})
_RESTING = frozenset({Activity.IDLE, Activity.STARTING})


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


class MoodEngine:
    """Stateless apart from a few timestamps it keeps on the state object."""

    @staticmethod
    def marks(state) -> dict:
        marks = getattr(state, "_mood_marks", None)
        if marks is None:
            marks = {"joy_at": -1e18, "sick_at": -1e18, "proud_at": -1e18}
            state._mood_marks = marks
        return marks

    # -- events -----------------------------------------------------------
    def apply(self, state, name: str, data: dict | None, now: float) -> None:
        """Let one signal move the session's feelings."""
        data = data or {}
        marks = self.marks(state)
        mood = energy = stress = focus = 0.0

        if name == Signal.TOOL_OK:
            mood, stress, focus, energy = 0.015, -0.02, 0.03, -0.004
        elif name == Signal.TOOL_ERROR:
            extra = min(max(int(data.get("streak", 1)) - 1, 0), 3)
            mood, stress, focus = -(0.06 + 0.03 * extra), 0.12, -0.05
        elif name == Signal.TESTS_PASSED:
            mood, stress = 0.15, -0.15
            marks["joy_at"] = now
        elif name == Signal.TESTS_FAILED:
            mood, stress = -0.08, 0.10
        elif name == Signal.COMMIT:
            mood = 0.12
        elif name == Signal.PROMPT:
            sentiment = data.get("sentiment")
            if sentiment == "praise":
                mood, stress = 0.25, -0.2
                marks["joy_at"] = now
            elif sentiment == "frustrated":
                mood, stress = -0.18, 0.2
        elif name == Signal.TURN_DONE:
            if not data.get("continued"):
                clean = not data.get("errors")
                mood, stress = (0.12 if clean else 0.04), -0.15
                if clean:
                    marks["joy_at"] = now
                    big = data.get("tools", 0) >= 10 or data.get("duration", 0) >= 300
                    if big:
                        marks["proud_at"] = now
        elif name == Signal.TURN_FAILED:
            mood, stress = -0.2, 0.25
            marks["sick_at"] = now
        elif name == Signal.PERMISSION_DENIED:
            mood = -0.08
        elif name == Signal.INTERRUPTED:
            mood = -0.05
            state.focus = 0.0
        elif name == Signal.COMPACT_DONE:
            stress, energy = -0.2, 0.1
        elif name == Signal.TASK_COMPLETED:
            mood = 0.05

        self.nudge(state, mood=mood, energy=energy, stress=stress, focus=focus)
        self.refresh(state, now)

    @staticmethod
    def nudge(state, *, mood=0.0, energy=0.0, stress=0.0, focus=0.0) -> None:
        state.mood = _clamp(state.mood + mood)
        state.energy = _clamp(state.energy + energy)
        state.stress = _clamp(state.stress + stress)
        state.focus = _clamp(state.focus + focus)

    # -- time -------------------------------------------------------------
    def tick(self, state, dt: float, now: float) -> None:
        """Advance feelings by ``dt`` seconds of the session's current situation."""
        if dt > 0:
            if state.working and not state.needs_user:
                state.energy = _clamp(state.energy - ENERGY_DRAIN_PER_S * dt)
                state.focus = _clamp(state.focus + FOCUS_RISE_PER_S * dt)
            else:
                state.energy = _clamp(state.energy + ENERGY_REST_PER_S * dt)
                state.focus = _clamp(state.focus - FOCUS_DECAY_PER_S * dt)
                state.stress = _clamp(state.stress - STRESS_DECAY_PER_S * dt)
            pull = 1.0 - math.exp(-dt / MOOD_RELAX_TAU)
            state.mood = _clamp(state.mood + (MOOD_BASELINE - state.mood) * pull)
        pct = state.context_pct
        if pct is not None and pct >= 0.7:
            state.stress = max(state.stress, _clamp((pct - 0.7) * 2.0))
        self.refresh(state, now)

    # -- summary ------------------------------------------------------------
    def refresh(self, state, now: float) -> None:
        state.emotion = self.emotion(state, now)

    def emotion(self, state, now: float) -> str:
        marks = self.marks(state)
        if state.activity == Activity.FAILED or now - marks["sick_at"] < SICK_SECS:
            return Emotion.SICK
        if state.context_pct is not None and state.context_pct >= 0.9:
            return Emotion.STUFFED
        if state.needs_user and state.needs_since and now - state.needs_since > ANXIOUS_AFTER:
            return Emotion.ANXIOUS
        if state.error_streak >= 3 or state.stress >= 0.75:
            return Emotion.FRUSTRATED
        if state.mood <= 0.25:
            return Emotion.SAD
        if state.stress >= 0.5:
            return Emotion.STRESSED
        if now - marks["joy_at"] < JOY_SECS:
            return Emotion.JOYFUL
        if state.energy <= 0.25:
            return Emotion.TIRED

        if state.working:
            if state.focus >= 0.7:
                return Emotion.FOCUSED
            if state.mood < 0.4:
                return Emotion.DETERMINED
            if state.activity in _EXPLORING and state.mood >= 0.5:
                return Emotion.CURIOUS
            return Emotion.HAPPY if state.mood >= 0.7 else Emotion.CONTENT

        if state.activity in _RESTING and not state.needs_user:
            idle_for = now - state.activity_since if state.activity_since else 0.0
            if idle_for >= SLEEPY_AFTER:
                return Emotion.SLEEPY
            if idle_for >= BORED_AFTER:
                return Emotion.BORED
        if now - marks["proud_at"] < PROUD_SECS:
            return Emotion.PROUD
        return Emotion.HAPPY if state.mood >= 0.7 else Emotion.CONTENT
