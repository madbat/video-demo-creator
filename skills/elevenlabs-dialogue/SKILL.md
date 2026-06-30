---
name: elevenlabs-dialogue
description: Generate natural voice-over / narration audio with the ElevenLabs Text-to-Dialogue API. Use when producing a narrated demo video, podcast, audiobook, or any per-line voice-over where each line becomes its own mp3 and identical lines are cached (no re-billing). Sounds markedly better than plain text-to-speech. Reads ELEVENLABS_API_KEY from the environment.
---

# ElevenLabs Dialogue

Turn a list of lines (each with a `voice_id`) into spoken audio using ElevenLabs'
**Text-to-Dialogue** API — which produces more natural, expressive delivery than
the plain `/v1/text-to-speech` endpoint, even for single-voice narration.

## When to use

- Voice-over for a **demo video** (one mp3 per shot, timed to each slide).
- Multi-voice **dialogue** (podcasts, scenes) — each line carries its own voice.
- Any narration where you want a per-line, content-addressed cache so re-runs are
  free for unchanged lines.

## Prerequisites

```bash
pip install elevenlabs pydub        # pydub optional (cleaner concat); ffmpeg used otherwise
export ELEVENLABS_API_KEY=...        # never hardcode this in a committed file
```

The key lives in your environment. Instead of exporting it each session you can
put it in a **`.env`** file — `generate_dialogue.py` auto-loads `.env` from the
current directory or any parent (existing env vars win, so it never overrides an
exported key). Copy `.env.example` to `.env` and fill in the key; `.env` is
gitignored. Override the path with `ELEVENLABS_ENV_FILE` if needed.

```
ELEVENLABS_API_KEY=your-key-here
```

Find a cloned (or stock) voice id with:

```bash
curl -s -H "xi-api-key: $ELEVENLABS_API_KEY" https://api.elevenlabs.io/v1/voices \
  | python3 -c 'import sys,json;[print(v["voice_id"],v["name"],v.get("category")) for v in json.load(sys.stdin)["voices"]]'
```

## Generate

Input is a JSON **array** of `{ "text", "voice_id" }` items. Keep `[emotion]`
delivery tags (e.g. `[warm]`, `[calm]`) inline — they're English even for other
languages.

```bash
# one mp3 for the whole array:
python3 scripts/generate_dialogue.py --input lines.json --output out.mp3

# for a demo video, generate ONE file per shot so each slide is timed to its clip:
python3 scripts/generate_dialogue.py --input shot-01.json --output audio/01.mp3
```

`lines.json`:
```json
[
  { "text": "[warm] Welcome — here's how it works.", "voice_id": "VOICE_ID" }
]
```

Useful flags: `--list-chunks` (print the chunking plan, no API calls),
`--regen 3,7` (force-regenerate specific chunks), `--force` (drop the whole
cache), `--no-concat` (chunks only). The per-chunk cache lives in
`<output_dir>/.segments/<basename>/` — identical chunks are reused across runs,
so you're never billed twice for the same line.

## Verify (optional, recommended)

`verify_dialogue.py` transcribes each generated chunk back with **whisper.cpp**
and flags TTS glitches — stuck loops, skipped/over-long output, dead air — so you
catch a bad take before assembling the video.

```bash
WHISPER_CLI=~/whisper.cpp/build/bin/whisper-cli \
WHISPER_MODEL=~/whisper.cpp/models/ggml-base.bin \
WHISPER_LANG=en \
python3 scripts/verify_dialogue.py --cache-dir audio/.segments/01 --save-transcripts
```

For Swedish narration, point `WHISPER_MODEL` at a KB-Whisper ggml model and set
`WHISPER_LANG=sv` for the most accurate check. Verification is optional — skip it
if you don't have whisper.cpp installed.

## Disclosure

If you narrate with someone's **cloned** voice, the honest default is to say so
(e.g. open with a short "this is an AI using my cloned voice"). Use a clone only
with that person's consent.
