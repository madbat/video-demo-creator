#!/usr/bin/env python3
"""Verify generated dialogue chunks against the source JSON using whisper.cpp.

Transcribes each cached chunk with kb_whisper and flags suspect ones based on:
  - LOOP: a 3-gram repeats in transcript far more than in source (TTS got stuck)
  - LONG/SHORT: transcript length is way off from expected (loop or skip)
  - DIVERGE: similarity ratio against source is low

Usage:
  verify_dialogue.py --cache-dir .segments/my_demo [--save-transcripts]

Requires whisper.cpp + a ggml model for back-transcription. Point at them with
the WHISPER_CLI and WHISPER_MODEL env vars (or edit the defaults below):
  WHISPER_CLI=~/whisper.cpp/build/bin/whisper-cli \
  WHISPER_MODEL=~/whisper.cpp/models/ggml-base.bin \
  verify_dialogue.py --cache-dir .segments/my_demo
For Swedish narration a KB-Whisper ggml model gives the most accurate check.
"""

import argparse
import collections
import difflib
import json
import os
import re
import subprocess
import sys

# Configurable via env so this works on any machine. Defaults assume a
# whisper.cpp checkout in ~/whisper.cpp with a base ggml model.
WHISPER_CLI = os.path.expanduser(
    os.environ.get("WHISPER_CLI", "~/whisper.cpp/build/bin/whisper-cli")
)
WHISPER_MODEL = os.path.expanduser(
    os.environ.get("WHISPER_MODEL", "~/whisper.cpp/models/ggml-base.bin")
)
# Language for the verification transcription (Whisper code, e.g. "en", "sv").
WHISPER_LANG = os.environ.get("WHISPER_LANG", "en")


def strip_brackets(text):
    return re.sub(r"\[[^\]]*\]", "", text)


def normalize(text):
    text = strip_brackets(text)
    text = re.sub(r"[^\w\såäöÅÄÖ]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def transcribe(audio_path, threads=8):
    cmd = [WHISPER_CLI, "-m", WHISPER_MODEL, "-f", audio_path,
           "-l", WHISPER_LANG, "-np", "-nt", "-t", str(threads)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stderr[:300]
    return result.stdout.strip(), None


def audio_duration(audio_path):
    """Return duration in seconds, or None on failure."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def loop_score(transcript, source):
    """Catastrophic loops repeat 5+ times (TTS got stuck). Whisper artifacts and
    normal rhetorical repetition stay below this threshold."""
    def trigrams(text):
        words = text.split()
        return [" ".join(words[i:i+3]) for i in range(len(words)-2)]
    t_counts = collections.Counter(trigrams(transcript))
    s_counts = collections.Counter(trigrams(source))
    flagged = []
    for tg, c in t_counts.items():
        s_c = s_counts.get(tg, 0)
        # Require both a high absolute count and a clear excess over source
        if c >= 5 and c >= s_c + 3:
            flagged.append((tg, c, s_c))
    flagged.sort(key=lambda x: -x[1])
    return flagged


def main():
    p = argparse.ArgumentParser(description="Verify TTS chunks against source with whisper.cpp.")
    p.add_argument("--cache-dir", required=True, help="Path to .segments/{base}/ directory")
    p.add_argument("--input", help="Source JSON path (default: read from manifest)")
    p.add_argument("--save-transcripts", action="store_true",
                   help="Write SOURCE+TRANSCRIPT to chunk_{hash}.transcript.txt next to each chunk")
    p.add_argument("--only", help="Comma-separated 1-based chunk indices to verify (default: all)")
    args = p.parse_args()

    if not os.path.exists(WHISPER_CLI):
        print(f"ERROR: whisper-cli not found at {WHISPER_CLI}")
        sys.exit(1)
    if not os.path.exists(WHISPER_MODEL):
        print(f"ERROR: whisper model not found at {WHISPER_MODEL}")
        sys.exit(1)

    manifest_path = os.path.join(args.cache_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"ERROR: no manifest at {manifest_path}. Generate audio first.")
        sys.exit(1)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    input_path = args.input or manifest["input_file"]
    with open(input_path, "r", encoding="utf-8") as f:
        inputs = json.load(f)

    only = None
    if args.only:
        only = {int(x.strip()) for x in args.only.split(",")}

    # Pre-compute audio duration per chunk to establish a chars/sec baseline.
    # TTS that gets stuck adds dead air or garbled noise at the end, inflating
    # duration without inflating the recognized transcript — so duration vs
    # source-char-count is a stronger signal than transcript-vs-source alone.
    durations = {}
    for rec in manifest["chunks"]:
        audio = os.path.join(args.cache_dir, rec["audio_file"])
        if os.path.exists(audio):
            durations[rec["index"]] = audio_duration(audio)
    rates = []
    for rec in manifest["chunks"]:
        d = durations.get(rec["index"])
        if d and d > 0:
            rates.append(rec["char_count"] / d)  # chars per second
    median_rate = sorted(rates)[len(rates)//2] if rates else None

    print(f"Verifying chunks in {args.cache_dir}")
    print(f"  whisper model: {os.path.basename(WHISPER_MODEL)}")
    if median_rate:
        print(f"  median TTS rate: {median_rate:.1f} chars/sec")
    suspicious = []
    for rec in manifest["chunks"]:
        idx = rec["index"]
        if only and idx not in only:
            continue
        audio = os.path.join(args.cache_dir, rec["audio_file"])
        if not os.path.exists(audio):
            print(f"  Chunk {idx:2d}: MISSING ({rec['audio_file']})")
            continue
        source_raw = " ".join(inputs[i]["text"] for i in range(rec["line_start"], rec["line_end"]+1))
        source = normalize(source_raw)

        print(f"  Chunk {idx:2d}: transcribing...", end=" ", flush=True)
        transcript_raw, err = transcribe(audio)
        if transcript_raw is None:
            print(f"WHISPER ERROR: {err}")
            continue
        transcript = normalize(transcript_raw)

        if args.save_transcripts:
            tpath = os.path.join(args.cache_dir, f"chunk_{rec['text_hash'][:12]}.transcript.txt")
            with open(tpath, "w", encoding="utf-8") as tf:
                tf.write(f"=== SOURCE (lines {rec['line_start']}-{rec['line_end']}) ===\n")
                tf.write(source_raw)
                tf.write(f"\n\n=== TRANSCRIPT ===\n")
                tf.write(transcript_raw)
                tf.write("\n")

        s_len = max(1, len(source))
        ratio = len(transcript) / s_len
        sim = difflib.SequenceMatcher(None, source, transcript).ratio()
        loops = loop_score(transcript, source)

        # Actionable signals (objective): catastrophic loops inflate transcript
        # length 1.5x+; skipped/muted output cuts it below 0.5x; stuck phrases
        # show as trigrams repeated 5+ times; dead-air at chunk end shows up as
        # a much lower chars/sec rate than the episode median.
        actionable = []
        if ratio > 1.5:
            actionable.append(f"LONG x{ratio:.2f}")
        if ratio < 0.5:
            actionable.append(f"SHORT x{ratio:.2f}")
        if loops:
            tg, c, sc = loops[0]
            actionable.append(f"LOOP '{tg}' x{c} (src x{sc})")
        dur = durations.get(idx)
        if dur and median_rate:
            chunk_rate = rec["char_count"] / dur
            if chunk_rate < median_rate * 0.7:
                actionable.append(f"SLOW {chunk_rate:.1f} cps vs median {median_rate:.1f}")
        # DIVERGE is informational — whisper normalization differences alone
        # routinely produce sim < 0.3 even on perfectly delivered audio.
        diverge = f"DIVERGE sim={sim:.2f}" if sim < 0.35 else None

        if actionable:
            print("  ".join(actionable) + (f"  ({diverge})" if diverge else ""))
            suspicious.append((idx, rec, actionable, transcript_raw))
        elif diverge:
            print(f"ok (low sim={sim:.2f}, len_ratio={ratio:.2f}) -- inspect transcript if curious")
        else:
            print(f"ok (sim={sim:.2f}, len_ratio={ratio:.2f})")

    print()
    if not suspicious:
        print("All checked chunks look clean.")
        return
    print(f"=== {len(suspicious)} suspect chunk(s) ===")
    regens = []
    for idx, rec, flags, t in suspicious:
        print(f"  Chunk {idx} (lines {rec['line_start']}-{rec['line_end']}, hash {rec['text_hash'][:12]})")
        for fl in flags:
            print(f"    - {fl}")
        snippet = t[:240].replace("\n", " ")
        print(f"    transcript: {snippet}...")
        regens.append(str(idx))
    print()
    print(f"Re-generate suspect chunks with:")
    print(f"  python3 generate_dialogue.py --input {manifest['input_file']} \\")
    print(f"    --output {manifest['output_file']} --regen {','.join(regens)}")


if __name__ == "__main__":
    main()
