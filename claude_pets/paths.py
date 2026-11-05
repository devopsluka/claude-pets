"""Filesystem locations used by Claude Pets.

Kept dependency-free (plain ``os.path`` strings) because the hook client
imports it on every Claude Code hook event and has to start fast.
"""

import os

APP_NAME = "claude-pets"

_HOME = os.path.expanduser("~")


def _xdg(var, *default):
    value = os.environ.get(var)
    if value and os.path.isabs(value):
        return value
    return os.path.join(_HOME, *default)


#: Root of the source checkout / install (the directory that holds ``claude_pets/``).
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_RUNTIME_BASE = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(
    "/tmp", "%s-%d" % (APP_NAME, os.getuid())
)
#: Volatile per-login state: socket, pid file, "stopped" flag.
RUNTIME_DIR = os.path.join(_RUNTIME_BASE, APP_NAME)
SOCKET_PATH = os.path.join(RUNTIME_DIR, "daemon.sock")
PID_FILE = os.path.join(RUNTIME_DIR, "daemon.pid")
SPAWN_LOCK = os.path.join(RUNTIME_DIR, "spawn.lock")
#: Present while the user has stopped the pets for this login session
#: (``claude-pets stop``); the hook client must not respawn the daemon.
STOPPED_FLAG = os.path.join(RUNTIME_DIR, "stopped")

CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DATA_DIR = os.path.join(_xdg("XDG_DATA_HOME", ".local", "share"), APP_NAME)
#: One JSON profile per pet (design + stats), keyed by project.
PETS_DIR = os.path.join(DATA_DIR, "pets")
#: Sprite-sheet skins (Codex pet atlas format).
SKINS_DIR = os.path.join(DATA_DIR, "skins")
#: Stable path the hooks point at; a symlink to APP_ROOT made by the installer.
INSTALL_LINK = os.path.join(DATA_DIR, "app")

STATE_DIR = os.path.join(_xdg("XDG_STATE_HOME", ".local", "state"), APP_NAME)
LOG_FILE = os.path.join(STATE_DIR, "daemon.log")

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(_HOME, ".claude")
CLAUDE_SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
CLAUDE_SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")
CLAUDE_PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
CLAUDE_SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")


def ensure_runtime_dir():
    os.makedirs(RUNTIME_DIR, mode=0o700, exist_ok=True)
    return RUNTIME_DIR


def ensure_dirs():
    ensure_runtime_dir()
    for path in (CONFIG_DIR, DATA_DIR, PETS_DIR, SKINS_DIR, STATE_DIR):
        os.makedirs(path, exist_ok=True)
