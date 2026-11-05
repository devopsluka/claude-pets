"""Persistent pet profiles.

A pet belongs to a *project* (a working directory), not to a single session:
open Claude Code in the same project tomorrow and the same friend shows up,
with its name, looks, level and bond intact. A second concurrent session in
the same project gets a sibling ("#2").
"""

import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field

from . import paths
from .render.color import is_hex
from .render.creature import (ACCENTS, ACCESSORIES, ALL_SPECIES, COATS, LEGEND_NAMES, LEGENDS, PATTERNS,
                              SIGNATURE_ACCENT, SPECIES, SPECIES_ORDER, Design)

NAMES = (
    "Mochi", "Pixel", "Biscuit", "Nori", "Tofu", "Pico", "Byte", "Kiwi", "Miso", "Pesto", "Waffle",
    "Ziggy", "Luna", "Bean", "Sprout", "Cosmo", "Pebble", "Noodle", "Tango", "Maple", "Juno", "Fig",
    "Otto", "Pip", "Rolo", "Sushi", "Taro", "Yuzu", "Mango", "Dumpling", "Pretzel", "Olive", "Peanut",
    "Bao", "Clover", "Nugget", "Poppy", "Rune", "Sesame", "Tater", "Udon", "Wasabi", "Zest", "Ember",
    "Fern", "Gizmo", "Hazel", "Indy",
)
PERSONALITIES = ("playful", "calm", "curious", "sleepy", "brave", "shy")
#: who can hatch for a new project: the animals, the legends, or anyone
CASTS = ("animals", "legends", "mixed")


def pool_for(cast):
    return {"animals": SPECIES_ORDER, "legends": LEGENDS}.get(cast, ALL_SPECIES)


def name_for(species, seed_text):
    """A legend goes by its own name; everybody else gets one picked for them."""
    if species in LEGEND_NAMES:
        return LEGEND_NAMES[species]
    d = _digest("name:" + seed_text)
    return NAMES[int.from_bytes(d[:2], "big") % len(NAMES)]


def _digest(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).digest()


def normalize_cwd(cwd):
    return os.path.normpath(cwd) if cwd else "~"


def pet_key(cwd, index=1):
    """Stable id for the ``index``-th pet of a project."""
    cwd = normalize_cwd(cwd)
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(cwd).lower()).strip("-") or "home"
    suffix = "" if index <= 1 else "-%d" % index
    return "%s%s-%s" % (slug[:40], suffix, _digest("%s#%d" % (cwd, index)).hex()[:8])


def default_design(seed_text, cast="animals"):
    d = _digest(seed_text)
    pool = pool_for(cast)
    species = pool[d[0] % len(pool)]
    fur, belly, extra = COATS[species][d[1] % len(COATS[species])]
    patterns = SPECIES[species]["patterns"]
    pattern = patterns[d[2] % len(patterns)] if d[3] % 3 == 0 else "plain"
    legend = species in LEGENDS                    # legends come as themselves
    accessory = ACCESSORIES[1 + d[4] % (len(ACCESSORIES) - 1)] if (d[5] % 5 < 2 and not legend) else "none"
    accent = SIGNATURE_ACCENT.get(species) or ACCENTS[d[6] % len(ACCENTS)]
    return Design(species=species, fur=fur, belly=belly, extra=extra, accent=accent,
                  pattern=pattern, accessory=accessory)


def level_for(xp):
    return int(math.sqrt(max(0, xp) / 25.0)) + 1


def xp_for(level):
    return 25 * (level - 1) ** 2


def sanitize_design(data, fallback):
    """Build a Design from untrusted JSON, falling back field by field."""
    out = asdict(fallback)
    if isinstance(data, dict):
        if data.get("species") in SPECIES:
            out["species"] = data["species"]
        for key in ("fur", "belly", "accent", "eye", "cheek"):
            if is_hex(data.get(key)):
                out[key] = data[key]
        if data.get("extra") == "" or is_hex(data.get("extra")):
            out["extra"] = data["extra"]
        if data.get("pattern") in PATTERNS:
            out["pattern"] = data["pattern"]
        if data.get("accessory") in ACCESSORIES:
            out["accessory"] = data["accessory"]
    return Design(**out)


def apply_changes(profile, changes, rng=None):
    """Apply design/name edits (from the studio, the CLI or ``/pet design``).

    ``changes`` maps field -> value; unknown or invalid entries are reported,
    valid ones are applied. Returns ``(changed_fields, errors)``.
    """
    import random as _random

    changed, errors = [], []
    design = asdict(profile.design)
    changes = dict(changes or {})
    if changes.pop("random", False):
        rng = rng or _random.Random()
        species = rng.choice(ALL_SPECIES)
        fur, belly, extra = rng.choice(COATS[species])
        design.update(species=species, fur=fur, belly=belly, extra=extra,
                      accent=SIGNATURE_ACCENT.get(species) or rng.choice(ACCENTS),
                      pattern=rng.choice(SPECIES[species]["patterns"]),
                      accessory=rng.choice(ACCESSORIES) if rng.random() < 0.6 and species not in LEGENDS else "none")
        changed.append("random")
    explicit_coat = any(k in changes for k in ("fur", "belly", "extra", "coat"))
    species_before = profile.design.species
    for key, value in changes.items():
        if key == "name":
            text = str(value).strip()
            if 1 <= len(text) <= 24:
                profile.name = text
                changed.append(key)
            else:
                errors.append("name must be 1-24 characters")
        elif key == "personality":
            if value in PERSONALITIES:
                profile.personality = value
                changed.append(key)
            else:
                errors.append("personality must be one of: %s" % ", ".join(PERSONALITIES))
        elif key == "species":
            if value not in SPECIES:
                errors.append("species must be one of: %s" % ", ".join(ALL_SPECIES))
                continue
            if value != design["species"] and not explicit_coat:
                design["fur"], design["belly"], design["extra"] = COATS[value][0]
            if value != design["species"] and "accent" not in changes and value in SIGNATURE_ACCENT:
                design["accent"] = SIGNATURE_ACCENT[value]
            design["species"] = value
            changed.append(key)
        elif key == "coat":
            try:
                coats = COATS[changes.get("species", design["species"])]
                design["fur"], design["belly"], design["extra"] = coats[int(value) % len(coats)]
                changed.append(key)
            except (KeyError, TypeError, ValueError):
                errors.append("coat must be a number")
        elif key in ("fur", "belly", "accent", "eye", "cheek", "extra"):
            if is_hex(value) or (key == "extra" and value == ""):
                design[key] = value
                changed.append(key)
            else:
                errors.append("%s must be a hex colour like #F97316" % key)
        elif key == "pattern":
            if value in PATTERNS:
                design["pattern"] = value
                changed.append(key)
            else:
                errors.append("pattern must be one of: %s" % ", ".join(PATTERNS))
        elif key == "accessory":
            if value in ACCESSORIES:
                design["accessory"] = value
                changed.append(key)
            else:
                errors.append("accessory must be one of: %s" % ", ".join(ACCESSORIES))
        else:
            errors.append("unknown field: %s" % key)
    if design["pattern"] not in SPECIES[design["species"]]["patterns"]:
        if "pattern" in changes:
            errors.append("%s does not come in %s; using plain" % (design["species"], design["pattern"]))
        design["pattern"] = "plain"
    profile.design = Design(**design)
    # Turning into (or out of) a legend renames the pet, unless it was named by hand.
    if design["species"] != species_before and "name" not in changes:
        auto_named = profile.name in NAMES or profile.name in LEGEND_NAMES.values()
        if auto_named:
            profile.name = name_for(design["species"], "%s#%d" % (profile.cwd, profile.index))
            changed.append("name")
    return changed, errors


@dataclass
class Profile:
    key: str
    cwd: str = ""
    index: int = 1
    name: str = "Mochi"
    personality: str = "playful"
    design: Design = field(default_factory=Design)
    home: float = -1.0          # preferred x as a fraction of the screen width; <0 = unset
    perch: float = -1.0         # y as a fraction of screen height when gravity is off
    hidden: bool = False
    stats: dict = field(default_factory=dict)
    persistent: bool = True

    @property
    def project(self):
        base = os.path.basename(normalize_cwd(self.cwd)) or "home"
        return base if self.index <= 1 else "%s #%d" % (base, self.index)

    @property
    def xp(self):
        return int(self.stats.get("xp", 0))

    @property
    def level(self):
        return level_for(self.xp)

    def bump(self, stat, amount=1):
        self.stats[stat] = self.stats.get(stat, 0) + amount

    def add_xp(self, amount):
        """Returns the new level if this crossed a level boundary, else 0."""
        before = self.level
        self.stats["xp"] = self.xp + int(amount)
        return self.level if self.level > before else 0

    def to_json(self):
        return {
            "key": self.key, "cwd": self.cwd, "index": self.index, "name": self.name,
            "personality": self.personality, "design": asdict(self.design), "home": self.home,
            "perch": self.perch, "hidden": self.hidden, "stats": self.stats,
        }


class Store:
    def __init__(self, pets_dir=None, cast="animals"):
        self.dir = pets_dir or paths.PETS_DIR
        self.cast = cast if cast in CASTS else "animals"

    def _path(self, key):
        return os.path.join(self.dir, key + ".json")

    def fresh(self, cwd, index=1):
        cwd = normalize_cwd(cwd)
        key = pet_key(cwd, index)
        seed = "%s#%d" % (cwd, index)
        d = _digest("name:" + seed)
        design = default_design(seed, self.cast)
        return Profile(
            key=key, cwd=cwd, index=index, name=name_for(design.species, seed),
            personality=PERSONALITIES[d[2] % len(PERSONALITIES)],
            design=design,
            stats={"born": time.time(), "xp": 0, "sessions": 0, "turns": 0, "tools": 0, "pets": 0, "treats": 0},
        )

    def load_key(self, key):
        try:
            with open(self._path(key), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        base = self.fresh(data.get("cwd") or "", int(data.get("index") or 1))
        base.key = key
        if isinstance(data.get("name"), str) and data["name"].strip():
            base.name = data["name"].strip()[:24]
        if data.get("personality") in PERSONALITIES:
            base.personality = data["personality"]
        base.design = sanitize_design(data.get("design"), base.design)
        for attr in ("home", "perch"):
            if isinstance(data.get(attr), (int, float)):
                setattr(base, attr, float(data[attr]))
        base.hidden = bool(data.get("hidden", False))
        if isinstance(data.get("stats"), dict):
            base.stats.update({k: v for k, v in data["stats"].items() if isinstance(v, (int, float))})
        return base

    def get(self, cwd, index=1, persistent=True):
        profile = self.load_key(pet_key(cwd, index))
        if profile is None:
            profile = self.fresh(cwd, index)
            profile.persistent = persistent
            if persistent:
                self.save(profile)
        return profile

    def save(self, profile):
        if not profile.persistent:
            return
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path(profile.key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(profile.to_json(), fh, indent=2)
            fh.write("\n")
        os.replace(tmp, self._path(profile.key))

    def all(self):
        try:
            names = sorted(os.listdir(self.dir))
        except OSError:
            return []
        out = []
        for name in names:
            if name.endswith(".json"):
                profile = self.load_key(name[:-5])
                if profile is not None:
                    out.append(profile)
        return out

    def find(self, query):
        """Find a profile by key, pet name, project name or directory."""
        if not query:
            return None
        q = query.strip().lower()
        profiles = self.all()
        for test in (
            lambda p: p.key.lower() == q,
            lambda p: p.name.lower() == q,
            lambda p: p.project.lower() == q,
            lambda p: normalize_cwd(p.cwd).lower() == normalize_cwd(query).lower() and p.index == 1,
            lambda p: q in p.key.lower() or q in p.name.lower(),
        ):
            for profile in profiles:
                if test(profile):
                    return profile
        return None
