"""How a pet talks: alternative lines for personalities that have their own voice.

Only the *wording* changes — anything factual the stock line carries (a count,
a file name, an error) is passed in as a format field and kept. A personality
with no entry here talks in the ordinary cheerful way.
"""

SNARKY = {
    "fresh": ("A clean slate. Try not to ruin it.", "Fresh start. Again."),
    "praise": ("I know.", "Obviously.", "Took you long enough to notice."),
    "frustrated": ("Don't look at me like that.", "Fine. I'll fix it. Again.", "Deep breaths. For you, not me."),
    "streak_ok": ("×{n} in a row. Don't get used to it.", "{n} without a mistake. Suspicious."),
    "streak_err": ("{n} failures in a row. Impressive, in a way.", "Failure ×{n}. Same plan again?",
                   "{n} in a row. Maybe read the error?"),
    "tests_passed": ("Tests passed. Shocking.", "Green. Don't celebrate yet.", "They pass. Mark the calendar."),
    "tests_failed": ("Tests failed. Who could have predicted.", "Red again. Charming.", "Failed. I'm not surprised."),
    "commit": ("Committed. No take-backs.", "Committed. Bold.", "In the history forever now."),
    "your_turn": ("Your move. Take your time. Or don't.", "Waiting on you, as usual.",
                  "Your turn. I'll be here. Judging."),
    "denied": ("Fine. Your loss.", "Not that, then. Noted.", "As you wish."),
    "turn_failed": ("Something broke. Not me. — {error}", "Well. That went badly. — {error}"),
    "interrupted": ("Stopping. Make up your mind.", "Oh, now you stop it."),
    "helper": ("Calling for help. Again.", "Delegating. Very executive."),
    "helpers": ("{n} helpers. A whole committee.", "Sending in {n} interns."),
    "compact": ("Forgetting things on purpose now.", "Squeezing memory. Some of it was useless anyway."),
    "compact_done": ("Lighter. Fewer bad ideas to remember.", "Much better. I forgot the boring parts."),
    "context_high": ("{pct}% full. Try being concise.", "{pct}% context. Someone talks too much."),
    "question": ("A question for you. Try to keep up.", "I need an answer. Today, ideally."),
    "input": ("Your input. If it's not too much trouble.", "I need you. Briefly."),
    "permission": ("Permission, please. I'll wait.", "Your OK. Whenever you're ready."),
    "done": ("Done. You're welcome.", "Done. Finally.", "Finished. Try to contain yourself."),
    "done_errors": ("Done. Eventually.", "Done — with a few accidents along the way.", "Done. Don't ask how."),
    "aside": ("{detail}. Bold choice.", "{detail}… if you insist.", "{detail}. Let's see how this goes.",
              "{detail}. Again.", "{detail}. I'd have done it differently."),
}

VOICES = {"snarky": SNARKY}

#: an aside on what the session is doing: at most this often, and only this share of the time
ASIDE_EVERY = 40.0
ASIDE_CHANCE = 0.35


def line(personality, key, rng, default, **fields):
    """The ``key`` line in this personality's voice, or ``default`` if it has none."""
    options = VOICES.get(personality, {}).get(key)
    if not options:
        return default
    try:
        return rng.choice(options).format(**fields)
    except (KeyError, IndexError, ValueError):
        return default


def has_voice(personality):
    return personality in VOICES
