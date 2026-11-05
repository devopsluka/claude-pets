---
name: pet
description: Claude Pets — the desktop pet friends that live beside every Claude Code session. Use when the user types /pet, or asks what their pets are doing or feeling, wants to hide/show them, give one a treat, rename or restyle one (/pet design …), or change a pet setting.
argument-hint: "[status | design [look…] | name <name> | hide [minutes] | show | treat | say <text> | config <key> <value> | demo | doctor]"
allowed-tools: Bash(claude-pets:*), Bash(~/.local/share/claude-pets/app/bin/claude-pets:*)
---

# /pet — Claude Pets

Every open Claude Code session has a pet on the desktop that acts out what the
session is doing (thinking, reading, editing, running commands, waiting for
permission, done…) and how it is feeling (energy, mood, stress, focus, context
fullness). They are driven by the `claude-pets` daemon; you control it with the
`claude-pets` CLI (fallback path: `~/.local/share/claude-pets/app/bin/claude-pets`).

The pet of **this** session is the default target of every command, because the
CLI reads `CLAUDE_CODE_SESSION_ID` from the environment — you never need to
pass a target unless the user names another pet or project.

User's request: $ARGUMENTS

## What to run

| The user wants | Run |
|---|---|
| nothing specific / "status" / "how are they?" | `claude-pets status` |
| design studio (GUI) — "design" with no description | `claude-pets design` (opens a window; run it in the background) |
| a new look described in words — "design a purple dragon with a crown" | see **Designing from a description** |
| a random look | `claude-pets design --random` |
| rename — "name Ember" | `claude-pets design --set name=Ember` |
| hide / show | `claude-pets hide [minutes]` (default 60) · `claude-pets show` |
| treat | `claude-pets treat` |
| poke it (pets an animal; a legend does its signature move) | `claude-pets poke [pet]` |
| turn it into a legend — "make him Mike Tyson" | `claude-pets design --set species=tyson` (also `snoop`, `pablo`, `einstein`, `tesla`, `arnold`, `trump`, `melania`, `miku`, `freddie`, `dolly`) |
| see all the legends in action | `claude-pets demo legends --for 120` |
| make it say something | `claude-pets say <text>` |
| jump to a pet's terminal | `claude-pets focus [pet]` |
| settings | `claude-pets config` (list) · `claude-pets config <key> <value>` |
| see them act without real work | `claude-pets demo` · `claude-pets demo --stop` |
| something is wrong | `claude-pets doctor` |
| stop / start everything | `claude-pets stop` · `claude-pets start` |
| every pet ever met | `claude-pets list` |

Settings worth knowing: `scale` (0.6–2.0), `bubbles` (all / important / off),
`gravity` (false = pets stay where you drop them), `wander`, `social`,
`sticker_rim`, `headless` (pets for `claude -p` runs), `sleep_after` (seconds),
`floor_offset` (px), `theme` (auto / dark / light), `click` (`terminal` = a
click raises the session's terminal, `pet` = a click pets it), `cast` (who
hatches for new projects: `animals`, `legends` or `mixed`).

**Legends** (Mike Tyson, Snoop Dogg, Pablo Escobar, Albert Einstein, Nikola
Tesla) are identities that are not pets: poking one (scroll / middle-click /
`claude-pets poke`) triggers its signature move instead of petting — Mike
punches, Snoop smokes, Pablo does a line, Einstein gets an idea, Tesla throws
lightning. For a legend the colour fields mean outfit (`fur`), skin (`belly`),
hair (`extra`) and signature colour (`accent`).

## Designing from a description

1. Run `claude-pets design --options` once to see the exact species, coat
   presets, patterns (they depend on the species) and accessories.
2. Translate the description into fields and apply them in one command, e.g.
   `claude-pets design --set species=dragon --set fur=#8B5CF6 --set belly=#FFE9C7 --set accessory=crown --set name=Ember`
   Fields: `name`, `species`, `coat` (preset number), `fur`, `belly`, `accent`
   (accessory colour), `extra` (detail colour: fox socks, gills, horns, beak,
   robot glow), `eye`, `cheek`, `pattern`, `accessory`, `personality`.
   Colours are hex. Pick a belly a few shades lighter than the fur.
3. The pet on the desktop changes instantly. Report the result in one line
   (name, species, the notable choices) and mention `claude-pets design` opens
   the visual studio for fine-tuning.

## Style

Keep answers short and warm — one or two lines, no tables unless the user asks
for the full status. Mouse tips, if useful: click a pet to jump to its
session's terminal, scroll over it (or middle-click) to pet it, drag to move
it, hover for its status card, right-click for its menu.
