# Claude Pets

Desktop pet friends for your Claude Code sessions. Every session you open gets
its own little creature at the bottom of your screen that acts out what the
session is **doing** and how it is **feeling** — so one glance tells you which
session is working, which one is stuck waiting for you, and which one just
finished.

Inspired by the OpenAI Codex pet, with a few things it does not do:

- **One pet per session**, not one for the whole app — five sessions, five friends.
- **Pets belong to projects.** Open the same project tomorrow and the same pet
  comes back with its name, look, level and bond. A second session in the same
  project gets a sibling.
- **Feelings, not just states.** Energy, mood, stress and focus build up from
  what actually happens (clean streaks, failing commands, long runs, your tone,
  a filling context window) and change the pet's face, posture and behaviour.
- **They show their work**: laptop for edits, book and glasses for reading,
  magnifier for searches, a terminal for commands, a globe for the web, a hard
  hat and a crew of mini-helpers while subagents run, a `!` sign when it needs
  your permission, a party hat when a big turn lands.
- **They are friends**: idle pets stroll over to greet each other and cheer
  when a neighbour finishes something big.
- **Design studio and `/pet design`**: restyle any pet by clicking, or just
  describe it ("a purple dragon with a crown called Ember").
- **Click a pet to jump to its terminal** — even on Wayland, where apps
  normally cannot raise each other's windows.
- **Legends**: not every identity is a pet. Mike Tyson, Snoop Dogg, Pablo
  Escobar, Albert Einstein, Nikola Tesla, Arnold Schwarzenegger, Donald and
  Melania Trump, Hatsune Miku, Freddie Mercury and Dolly Parton can take a
  session too, and they do not get petted — they do their thing instead (see below).
- Drag, toss, pet and treat them; hover for a status card with a context meter.

## Install

```sh
./install.sh            # or: bin/claude-pets install
```

That adds silent hooks to `~/.claude/settings.json` (a timestamped backup is
written next to it), installs the `/pet` and `/pet-design` skills, links the
`claude-pets` command into `~/.local/bin`, and brings the pets out. Sessions
that are already open get pets too.

Requirements: Linux with X11 or XWayland (GNOME, KDE, …), Python 3 with
PyGObject / GTK 3 / Cairo — all present on a stock Fedora Workstation.
`claude-pets doctor` checks the lot.

Remove with `claude-pets uninstall` (`--purge` also deletes pet profiles).

## Living with them

| Do this | And |
|---|---|
| **click a pet** | **brings up the app its terminal lives in** — the right kitty window/tab, GNOME Terminal / Ptyxis / Console, a VS Code or other X11 window, the tmux pane (see below) |
| scroll over it / middle-click | pets it (hearts; a little mood boost) — a legend does its signature move instead |
| drag / toss | carry it anywhere; it drops, bounces and remembers the new spot |
| hover | status card: what it is doing, how it feels, energy / mood / focus, context %, tool counts |
| right-click | menu: go to terminal, treat, design, tuck away, bubbles, quit |

### What the pets tell you

| Session is… | The pet… |
|---|---|
| thinking | sits, scratches its head, `· · ·` thought bubble |
| reading / searching | reads a book with glasses / peers through a magnifier |
| editing | types on a laptop (headphones once it is "in the zone") |
| running a command / tests | pokes at a terminal; holds its breath for tests |
| browsing | watches a spinning globe |
| running subagents | puts on a hard hat and directs a crew of mini-pets |
| planning | ticks off a clipboard |
| **waiting for permission / asking you** | holds up a `!` / `?` sign and hops — more anxiously the longer you take |
| compacting | squeezes itself, papers flying |
| done | celebrates (confetti for big turns), plants a flag, then relaxes |
| hit an API error | sits dizzy with a thermometer |
| idle | strolls, grooms, hums, visits friends; naps in a nightcap after 10 minutes |

Feelings come on top: a clean streak makes it proud, three failures in a row
make it steam, praise in your prompt earns hearts, a sharp "still broken??"
makes it sheepish and determined, a long slog drains its energy (coffee mug),
and a context window past ~60 % shows as a rounder and rounder belly until it
tells you it is stuffed.

### Legends

Dark-comedy caricatures on the same rig. They report the session exactly like
the animals do (laptop, book, sign…), but where a pet would purr they have a
signature move — it replaces petting, and it also fires at fitting moments:

| Legend | Poke it (instead of petting) | In a session |
|---|---|---|
| **Mike Tyson** | throws a punch — at whoever stands next to him, who sees stars for a second | punches a failing command ("Everybody has a plan until exit code 1"), shadow-boxes when idle, wears the belt after a big turn, greets friends with a jab |
| **Snoop Dogg** | takes a long drag and exhales a cloud | always has one lit; thinks by smoking; "Fo shizzle." when done |
| **Pablo Escobar** | does a line off a little mirror and comes up wired | sometimes powers up that way when you send a prompt; "Plata o plomo?" on permission prompts; stares into the distance when you keep him waiting; makes it rain cash after a big turn |
| **Albert Einstein** | gets an idea (lightbulb) | thinks at a chalkboard; the bulb lights when thinking turns into doing; tongue out when done |
| **Nikola Tesla** | throws lightning (neighbours get a jolt) | runs commands on a Tesla coil; a failing command electrocutes him; lights a bulb wirelessly when done; pigeons like him |
| **Arnold Schwarzenegger** | double-biceps flex | curls a dumbbell while commands run; flexes when tests pass; "Get to the choppa!" on an error streak; "I'll be back." when the session ends |
| **Donald Trump** | double thumbs-up ("TREMENDOUS!") | points at the crowd when idle; signs a commit (or a big turn) with a giant pen; "Fake errors!" on an error streak |
| **Melania Trump** | turns away and touches up her hat — poke again and you get the side-eye | a tiny golf clap when tests pass; a flat stare and "…" at errors; brushes off Donald whenever he comes near |
| **Hatsune Miku** | spins her leek, notes flying | sings when tests pass or a turn ends; pouts (twin tails droop) at errors; grooves when idle |
| **Freddie Mercury** | "Ay-oh!" and a fist pump | never without his half mic stand; strikes a pose with it on long runs; raises it like a sceptre when tests pass |
| **Dolly Parton** | winks — sparkles and "Hey there, honey!" | "Workin' 9 to 5" when the work starts; strums a guitar when a turn ends; admires her nails when idle |

Turn any pet into one with `claude-pets design --set species=tyson` (also
`snoop`, `pablo`, `einstein`, `tesla`, `arnold`, `trump`, `melania`, `miku`,
`freddie`, `dolly`), in the studio under **Who**, or with
`/pet design make him Snoop`. `claude-pets config cast legends` makes every
*new* project hatch a legend (`animals` = never, `mixed` = either, the
default); pets you already have keep their identity. `claude-pets demo legends`
puts all five on screen with pretend sessions.

## Commands

```
claude-pets                 status of every pet (same as `status`)
claude-pets design          open the Pet Design Studio for this session's pet
claude-pets design --set species=fox --set accessory=scarf --set name=Rune
claude-pets design --random | --show | --options
claude-pets hide [minutes]  · show · toggle
claude-pets treat [pet]     · say <text> · focus [pet] · poke [pet]
claude-pets config [key [value]]
claude-pets demo [n|legends] [--for SECONDS]   pretend sessions, to watch them work (--stop to end)
claude-pets gallery [dir]   render every species, face and pose to PNG sheets
claude-pets start | stop | restart | doctor | install | uninstall
```

Inside Claude Code: `/pet` (status, hide, treat, settings…) and
`/pet design <description>` or `/pet-design` to restyle the current session's
pet in words. A pet is addressed by its name, its project, a directory or a
session id; inside a session the default is always "my pet".

### Settings (`claude-pets config`)

| Key | Default | Meaning |
|---|---|---|
| `scale` | `1.0` | pet size, 0.6 – 2.0 |
| `bubbles` | `all` | `all`, `important` (needs-you / done / errors) or `off` |
| `theme` | `auto` | bubble and card colours: follow the desktop, or `dark` / `light` |
| `emoji` | `true` | emoji in bubbles |
| `sticker_rim` | `true` | light border so pets read on any background |
| `gravity` | `true` | `false`: pets stay wherever you drop them |
| `wander`, `social` | `true` | strolling; visiting each other |
| `headless` | `true` | pets for `claude -p` / SDK sessions too |
| `sleep_after` | `600` | idle seconds before a nap |
| `floor_offset` | `0` | raise the floor above the screen bottom (px), e.g. over a dock |
| `show_prompt` | `true` | latest prompt snippet in the hover card |
| `click` | `terminal` | what a click does: `terminal` (go to the session's terminal) or `pet` (then double-click goes to the terminal) |
| `cast` | `mixed` | who hatches for a new project: `animals`, `legends` or `mixed` |
| `exit_when_empty` | `180` | daemon quits this long after the last session closes |

Tip: bind `claude-pets toggle` to a keyboard shortcut (GNOME Settings →
Keyboard → Custom Shortcuts) to hide the pets for a screen share or a film.
They also hide by themselves while the screen is locked or the GNOME overview
is open.

## How it works

```
Claude Code session ──hooks──▶ bin/claude-pets-hook ──unix socket──▶ daemon
~/.claude/sessions/*.json ───────── registry watcher ─────────────▶   │
~/.claude/projects/**.jsonl ─────── transcript tailer ────────────▶   │
                                                                      ▼
                              tracker (what it is doing) + mood engine (how it feels)
                                                                      ▼
                              brain (behaviour, pose) ─▶ renderer ─▶ one tiny window per pet
```

- **Hooks** (`hooks_install.py`): 19 Claude Code events forward a trimmed
  JSON line to the daemon in ~20 ms; tool events are `async`, so nothing waits
  on them, and they print nothing, so nothing is added to your context. If the
  daemon is not running the hook starts it (unless you ran `claude-pets stop`).
- **Registry + transcripts**: sessions are also discovered from Claude Code's
  own session registry, and context-window usage is read from the transcript,
  so sessions without hooks still get a (coarser) pet.
- **Tracker / mood** (`tracker.py`, `mood.py`): a state machine per session
  plus four slow variables — energy, mood, stress, focus — summarised as one
  of 16 emotions.
- **Brain** (`brain.py`): picks the behaviour and produces a pose every frame.
- **Renderer** (`render/`): pets are drawn procedurally with Cairo from parts
  on one shared rig — 12 species, 11 human legends (`render/human.py`, with
  their behaviour in `legends.py`), 6 coat patterns, 11 accessories, any
  colours — so every pet is fully re-designable and there are no image assets.
- **Overlay** (`overlay.py`): each pet is a small transparent, click-through,
  override-redirect X11 window (through XWayland on Wayland), which is the one
  portable way to place something exactly, above everything, without a
  compositor extension. Frames are rasterised client-side and only the changed
  rectangle is sent to the X server; calm pets repaint a few times a second.

### Click → terminal, on Wayland too

Wayland does not let one app raise another's window unless it can present an
*activation token* proving the user just asked for it. A click on a pet is
exactly that: the daemon turns the click into a token (an X11
startup-notification id, which mutter also honours as an `xdg-activation`
token) and passes it to the terminal through whatever door it has
(`focus.py`):

| Terminal | How it is raised |
|---|---|
| kitty (remote control on) | a tiny kitten (`kitty_focus.py`) selects the session's window/tab and activates the OS window with the token |
| GNOME Terminal, Ptyxis, Console, Ghostty, Tilix | D-Bus application activation carrying the token |
| VS Code, JetBrains, xterm, anything on X11 / XWayland | EWMH activation of the window that owns the session (matched by process and project name) |
| tmux | selects the window and pane first, then raises the terminal of the attached client |
| anything else | rings the bell on the session's tty, so the desktop flags the window |

Design tokens (`render/tokens.py`) follow a primitive → semantic → component
structure; the direction ("Mascot Modern": flat, rounded, warm — orange
`#F97316`, green `#4ADE80`, violet `#8B5CF6`) came out of the `/design` skill's
brief for a pet/mascot product.

### Privacy

Everything stays on this machine. The hook trims payloads before they leave
the Claude process (file *names*, the first line of a command, a short prompt
snippet used for tone and the hover card); nothing is written to disk except
pet profiles (`~/.local/share/claude-pets/pets/`) and a small log
(`~/.local/state/claude-pets/daemon.log`). Speech bubbles are visible on your
screen and in screen shares — use `bubbles = important` or `claude-pets hide`
when that matters.

## Development

```sh
python3 -m unittest discover -s tests      # tracker, mood, hooks, brain, renderer, overlay
claude-pets gallery /tmp/pets              # eyeball the art
claude-pets demo 3                         # three scripted sessions on your desktop
claude-pets restart                        # pick up code changes (the install is a symlink to this checkout)
```

No screenshot tool on Wayland? `claude-pets status --json` lists each pet
window's `xid`; `import -window <xid> pet.png` (ImageMagick) captures exactly
what that window shows.

Layout: `claude_pets/` (`model.py` is the contract between the session core
and the desktop side), `bin/`, `skills/`, `assets/`, `tests/`.

Known limits: pets live on the primary monitor; raising a terminal relies on
the routes above (kitty needs `allow_remote_control` and `listen_on`; other
Wayland-native terminals without D-Bus activation only get the bell); a
fullscreen video does not hide them — use `claude-pets toggle`.
