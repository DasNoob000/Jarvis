# Jarvis

A voice assistant that lives in the macOS menu bar. Two claps wake it, you speak, it
answers aloud — and it can open apps, search the web, and look at your screen. Say the
cancel phrase and whatever it is doing stops immediately.

**Status: Phase 1 of 6.** The skeleton, config system, OS-adapter seam, menu-bar UI and
`.app` packaging are in place. Voice, model, and actions land in phases 2–4. See
[the build plan](#build-phases).

---

## How it is put together

macOS is the target. Development happens on Windows, so the code is split at a seam:

- **The engine** — wake detection, transcription, the model loop, speech, actions — is
  plain cross-platform Python. It runs and is tested on either OS.
- **`src/jarvis/platform_adapters/`** — the only code that knows what OS it is on.
  `macos.py` is rumps, LaunchAgents, `screencapture`, AppleScript and TCC preflight.
  `windows.py` is the same interface over pystray, `mss` and the registry.

`tests/test_import_boundary.py` fails the build if anything platform-specific leaks out
of that directory. The point is that almost everything can be verified before it
reaches a Mac, and the part that cannot is about two hundred lines.

```
src/jarvis/
  engine.py            state machine, activation lifecycle, cancellation
  events.py            State enum, event types, the bus
  config.py            TOML load + validate + first-run seeding
  secrets.py           env var -> keychain -> SDK profile
  audio/               capture, clap detection, VAD            (phase 2)
  stt/                 faster-whisper, cancel-phrase listener  (phase 2)
  llm/                 Claude client, tool loop, personality   (phase 3)
  tts/                 system / ElevenLabs / Piper backends    (phase 3)
  actions/             open app, browse, read the screen       (phase 4)
  routines/            startup routine                         (phase 5)
  ui/                  menu model, generated status icons
  platform_adapters/   the OS seam
```

### Threads

The UI toolkit takes the main thread and never gives it back, so:

| Thread | Runs |
|---|---|
| main | rumps / pystray run loop. Menu clicks post to the engine and return. |
| `jarvis-engine` | one asyncio loop; everything else |
| PortAudio callback | drops frames into a ring buffer, nothing more |
| workers | Whisper and TTS, via `asyncio.to_thread` |

One activation — wake to answer — is one `asyncio.Task`. The cancel phrase cancels
that task, which is what lets it interrupt a reply mid-sentence or a tool mid-run.

---

## Running from source

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,windows]"   # Windows
# .venv/bin/python -m pip install -e ".[dev,macos]"       # macOS
```

```bash
python -m jarvis
```

First run writes a config file and a copy of the personality prompt to your user
config directory and tells you where. `Reveal Config File` in the menu opens it.

Poke at individual pieces without the UI:

```bash
python tools/devcli.py info
```

```bash
python tools/devcli.py permissions
```

Run the tests:

```bash
python -m pytest
```

---

## Configuration

One TOML file, seeded from [`config/jarvis.example.toml`](config/jarvis.example.toml)
on first run:

| | |
|---|---|
| macOS | `~/Library/Application Support/Jarvis/jarvis.toml` |
| Windows | `%APPDATA%\Jarvis\jarvis.toml` |

Unknown keys are rejected rather than ignored — a typo stops the app with a readable
message instead of silently doing nothing.

**The personality lives in a separate plain-text file**,
[`config/personality.txt`](config/personality.txt), copied next to the config. It is
the system prompt and nothing else; editing it cannot break the app.

**API keys are never in the config file.** They are read from, in order:

1. `ANTHROPIC_API_KEY`
2. the OS keychain, service `Jarvis`, account `anthropic_api_key`
3. an `ant auth login` profile, resolved by the SDK

### Model settings worth knowing

Jarvis talks to `claude-opus-5` at `effort = "low"` — a spoken reply wants latency, not
depth. Two options in `[llm]` you may want:

- `fast_mode` — same model, up to ~2.5× output tokens/sec, at premium pricing
  ($10/$50 per MTok instead of $5/$25). Off by default.
- `refusal_fallbacks` — lets the server reroute a refused request instead of Jarvis
  falling silent. On by default; costs nothing when unused.

---

## Building the macOS app

```bash
cd packaging/macos && python setup_py2app.py py2app
```

Then drag `dist/Jarvis.app` to `/Applications`, and **read
[`packaging/macos/PERMISSIONS.md`](packaging/macos/PERMISSIONS.md) before first
launch** — macOS asks for four separate grants in three different ways, and one of
them (Screen Recording) will not work until you relaunch.

Two things that will bite you otherwise:

- Ad-hoc sign the bundle (`codesign --force --deep --sign - /Applications/Jarvis.app`)
  after every rebuild. macOS keys permissions to the code signature, so an unsigned app
  loses its grants each time you rebuild, for no visible reason.
- Running from source attributes permissions to your **terminal**, not to Jarvis.

Use `-A` for an alias build while iterating; it is far quicker and shares TCC grants
with the release build.

---

## Build phases

| | | |
|---|---|---|
| 1 | Skeleton, adapter seam, `.app` bundle, menu bar, permissions | **done** |
| 2 | Double-clap wake, VAD, local Whisper, cancel listener | next |
| 3 | Claude with tool use, personality, spoken replies | |
| 4 | Open apps, web search, screen reading | |
| 5 | Startup routine, Start-at-Login toggle | |
| 6 | Settings window, error handling, degradation | |

---

## Known rough edges

- **Speaker bleed.** The mic hears Jarvis's own voice, so the cancel listener can
  self-trigger. There is no echo cancellation; the mitigation in phase 2 is to pause
  playback on a candidate detection and confirm before acting. Headphones avoid it.
- **Clap false positives.** Door slams look like claps. `devcli clap-tune` (phase 2)
  calibrates the threshold against your room; expect to spend a few minutes on it.
- **AppleScript is off by default.** Narrow named actions always work. The general
  automation escape hatch is arbitrary code execution chosen by a language model, so
  it stays behind `actions.allow_automation` and an allowlist.
