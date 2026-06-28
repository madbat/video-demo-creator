# Claude Code — Demo Creator

A Claude Code **subagent** that turns a running app into a short, polished,
**narrated demo video** — it captures each feature as a screenshot, writes a
one-line voice-over per shot, generates the audio with ElevenLabs, and assembles
an `mp4` with ffmpeg. Its guiding rule: **what the viewer sees must match what
the narration says, in every shot.**

This repo bundles the agent together with the skills it relies on, so you can
drop the whole kit into `~/.claude/` and start making demos.

https://github.com/fltman/claude-code-demo-creator

## What's inside

| Component | Path | Role |
|---|---|---|
| **demo-creator** subagent | `agents/demo-creator.md` | Orchestrates the whole pipeline (scope → capture → narrate → voice-over → assemble → verify). |
| **`/demo-video`** command | `commands/demo-video.md` | Slash command that kicks off the agent in one line: `/demo-video http://localhost:5173`. |
| **elevenlabs-dialogue** skill | `skills/elevenlabs-dialogue/` | Generates per-shot narration audio via ElevenLabs Text-to-Dialogue, with a content-addressed cache + optional whisper.cpp verification. |
| **screenshot** skill | `skills/screenshot/` *(git submodule)* | Captures macOS screenshots / app windows non-interactively. Lives at [fltman/claude-code-skill-screenshot](https://github.com/fltman/claude-code-skill-screenshot). |

For **web apps** the agent prefers a **headed Playwright** browser (a headless
one renders blank WebGL/canvas/map panels); the screenshot skill covers
**native/desktop** apps.

## Install

```bash
# clone with the screenshot submodule
git clone --recurse-submodules https://github.com/fltman/claude-code-demo-creator.git
cd claude-code-demo-creator

# install the agent + command + skills for Claude Code (user scope)
mkdir -p ~/.claude/agents ~/.claude/skills ~/.claude/commands
cp agents/demo-creator.md   ~/.claude/agents/
cp commands/demo-video.md   ~/.claude/commands/
cp -R skills/elevenlabs-dialogue ~/.claude/skills/
cp -R skills/screenshot          ~/.claude/skills/
```

(Project scope works too — put them under `<project>/.claude/{agents,commands,skills}`
instead.)

## Prerequisites

```bash
# audio (ElevenLabs)
pip install elevenlabs pydub
export ELEVENLABS_API_KEY=...          # your key, from the environment — never committed

# video assembly
brew install ffmpeg                    # or your platform's ffmpeg

# web-app capture (the agent installs these per-run if missing)
npm i -g playwright && npx playwright install chromium

# optional: back-transcription verification of the narration
#   build whisper.cpp and grab a ggml model, then point the verifier at them:
#   WHISPER_CLI=~/whisper.cpp/build/bin/whisper-cli WHISPER_MODEL=~/whisper.cpp/models/ggml-base.bin
```

A macOS host is assumed for the screenshot skill (`screencapture`) and `open`.
The audio + ffmpeg + Playwright steps are cross-platform.

## Use it

Run the slash command:

```
/demo-video http://localhost:5173
```

…or just ask in plain language ("make a narrated demo video of my app at
http://localhost:5173"). Either way the agent will:

1. **Scope & confirm** — list the features (one shot each) and ask you for the
   **voice** (it offers your cloned ElevenLabs voice) and the **language**.
   Audio is the expensive, identity-sensitive step, so it never guesses these.
2. **Capture** one clean screenshot per feature → `demo/shots/NN-name.png`.
3. **Narrate** — one short line per shot in your language.
4. **Voice-over** — one mp3 per shot via the ElevenLabs dialogue skill.
5. **Assemble** — each slide held for its narration (+ a short pause), with
   fades, into `demo/<app>-demo.mp4`.
6. **Verify** — read frames back to confirm say == show, then open the result.

## Notes

- **Secrets:** `ELEVENLABS_API_KEY` is read from the environment and never
  written to committed files.
- **Cloned voices:** if you narrate with someone's cloned voice, the honest
  default is a short up-front disclosure, and only with their consent.
- **Cost control:** the dialogue cache is content-addressed — re-running only
  bills for lines whose text or voice changed.

## License

MIT © Anders Bjarby. The bundled **screenshot** skill is a separate project
([fltman/claude-code-skill-screenshot](https://github.com/fltman/claude-code-skill-screenshot))
included here as a submodule; see that repository for its terms.
