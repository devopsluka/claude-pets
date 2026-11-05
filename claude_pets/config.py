"""User configuration (``~/.config/claude-pets/config.json``)."""

import json
import os

from . import paths

DEFAULTS = {
    "enabled": True,          # false: hooks never start the daemon
    "scale": 1.0,             # pet size multiplier (0.6 .. 2.0)
    "bubbles": "all",         # all | important | off
    "theme": "auto",          # auto | dark | light  (bubbles and status card)
    "emoji": True,            # emoji prefixes in bubbles
    "sticker_rim": True,      # light border around pets so they read on any background
    "gravity": True,          # false: pets stay wherever you drop them
    "wander": True,           # idle pets stroll around
    "social": True,           # idle pets visit each other
    "headless": True,         # also show pets for `claude -p` / SDK sessions
    "floor_offset": 0,        # raise the "floor" above the screen bottom, px
    "sleep_after": 600,       # seconds of idle before a pet naps
    "show_prompt": True,      # show the latest prompt snippet in the hover card
    "click": "terminal",      # what a click does: "terminal" (go to the session's terminal) or "pet"
    "cast": "mixed",          # who hatches for a new project: "animals", "legends" or "mixed"
    "max_pets": 12,
    "exit_when_empty": 180,   # daemon exits after this many seconds without sessions (0 = never)
}


def load(path=None):
    cfg = dict(DEFAULTS)
    try:
        with open(path or paths.CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for key, value in data.items():
                if key in DEFAULTS and isinstance(value, type(DEFAULTS[key])) or (
                        key in ("scale",) and isinstance(value, (int, float))):
                    cfg[key] = value
    except (OSError, ValueError):
        pass
    cfg["scale"] = max(0.6, min(2.0, float(cfg["scale"])))
    if cfg["bubbles"] not in ("all", "important", "off"):
        cfg["bubbles"] = "all"
    if cfg["theme"] not in ("auto", "dark", "light"):
        cfg["theme"] = "auto"
    if cfg["click"] not in ("terminal", "pet"):
        cfg["click"] = "terminal"
    if cfg["cast"] not in ("animals", "legends", "mixed"):
        cfg["cast"] = "mixed"
    return cfg


def save(cfg, path=None):
    path = path or paths.CONFIG_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {k: cfg[k] for k in DEFAULTS if k in cfg}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def set_value(key, raw, path=None):
    """Set one key from a CLI string; returns the parsed value."""
    if key not in DEFAULTS:
        raise KeyError(key)
    default = DEFAULTS[key]
    if isinstance(default, bool):
        value = str(raw).strip().lower() in ("1", "true", "yes", "on")
    elif isinstance(default, int):
        value = int(raw)
    elif isinstance(default, float):
        value = float(raw)
    else:
        value = str(raw)
    cfg = load(path)
    cfg[key] = value
    save(cfg, path)
    return load(path)[key]
