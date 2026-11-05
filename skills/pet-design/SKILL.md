---
name: pet-design
description: Design a Claude Pet — restyle the desktop pet of this session (or any other pet) from a description, roll a random look, or open the visual Pet Design Studio. Use for /pet-design and for requests like "make my pet a purple dragon with a crown", "rename my pet", "give it glasses".
argument-hint: "[description of the look | random | studio]"
allowed-tools: Bash(claude-pets:*), Bash(~/.local/share/claude-pets/app/bin/claude-pets:*)
---

# /pet-design — design your Claude Pet

Request: $ARGUMENTS

The `claude-pets` CLI (fallback path `~/.local/share/claude-pets/app/bin/claude-pets`)
targets the pet of the current session by default.

- **No description, or "studio"** → run `claude-pets design` in the background.
  It opens the Pet Design Studio: live animated preview, species, coats,
  markings, accessories, custom colours, name and personality.
- **"random" / "surprise me"** → `claude-pets design --random`.
- **A description** →
  1. `claude-pets design --options` lists every species with its coat presets
     and allowed patterns, plus the accessories and personalities.
  2. Apply everything in one go, for example:
     `claude-pets design --set species=fox --set pattern=plain --set accessory=scarf --set accent=#38BDF8 --set name=Rune`
     Fields: `name`, `species`, `coat` (preset number), `fur`, `belly`,
     `accent`, `extra`, `eye`, `cheek`, `pattern`, `accessory`, `personality`.
     Colours are hex; choose a belly noticeably lighter than the fur, and an
     accent that contrasts with both.
  3. `claude-pets design --show` prints the current look if you need to check.
- **A legend** ("make him Mike Tyson / Snoop / Pablo / Einstein / Tesla") →
  `claude-pets design --set species=tyson` (or `snoop`, `pablo`, `einstein`,
  `tesla`). Legends are human characters, not pets: they take their own name
  unless one was set by hand, their colour fields mean outfit (`fur`), skin
  (`belly`), hair (`extra`) and signature colour (`accent`), and poking them
  triggers their signature move instead of petting.
- **Another pet** → add its name, project or directory as the first argument:
  `claude-pets design Mochi --set accessory=crown`.

The pet on the desktop updates immediately. Reply in one line describing the
new look.
