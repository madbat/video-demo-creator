#!/usr/bin/env python3
"""Generate dialogue audio with ElevenLabs Text-to-Dialogue API.

Per-chunk content-addressed cache: identical chunks across runs are reused
(no API call, no cost). Cache lives in {output_dir}/.segments/{basename}/.
Use --regen N[,M] to force-regenerate specific chunks; --force to drop all.
"""

import argparse
import hashlib
import json
import os
import sys

try:
    from elevenlabs import ElevenLabs
except ImportError:
    print("ERROR: elevenlabs package not installed. Run: pip install elevenlabs")
    sys.exit(1)

PYDUB_AVAILABLE = False
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    pass

MAX_CHARS_PER_CHUNK = 2000


def get_client():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY not set.")
        sys.exit(1)
    return ElevenLabs(api_key=api_key)


def chunk_hash(chunk):
    h = hashlib.sha256()
    for item in chunk:
        h.update(item["voice_id"].encode("utf-8"))
        h.update(b"\x00")
        h.update(item["text"].encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


def split_into_chunks(inputs, max_chars):
    """Returns (chunks, starts) where starts[i] is the 0-based line index of chunks[i][0]."""
    chunks, starts = [], []
    current, cur_chars, cur_start = [], 0, 0
    for line_idx, item in enumerate(inputs):
        item_chars = len(item["text"])
        if current and cur_chars + item_chars > max_chars:
            chunks.append(current)
            starts.append(cur_start)
            current, cur_chars, cur_start = [], 0, line_idx
        current.append(item)
        cur_chars += item_chars
    if current:
        chunks.append(current)
        starts.append(cur_start)
    return chunks, starts


def cache_dir_for(output_path):
    base = os.path.splitext(os.path.basename(output_path))[0]
    parent = os.path.dirname(os.path.abspath(output_path)) or "."
    return os.path.join(parent, ".segments", base)


def generate_chunk(client, chunk):
    try:
        response = client.text_to_dialogue.convert(inputs=chunk)
        data = b""
        for c in response:
            data += c
        return data
    except Exception as e:
        print(f"  API error: {e}")
        return None


def concatenate(audio_files, output_path):
    if PYDUB_AVAILABLE:
        combined = AudioSegment.empty()
        for f in audio_files:
            combined += AudioSegment.from_mp3(f)
        combined.export(output_path, format="mp3")
        return True
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for af in audio_files:
            f.write(f"file '{af}'\n")
        listfile = f.name
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", listfile, "-c", "copy", output_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"ERROR: ffmpeg failed: {result.stderr}")
            return False
        return True
    finally:
        os.unlink(listfile)


def prune_orphans(cache_dir, keep_filenames):
    keep = set(keep_filenames) | {"manifest.json"}
    keep |= {f for f in os.listdir(cache_dir) if f.endswith(".transcript.txt")}
    for f in os.listdir(cache_dir):
        if f not in keep and (f.endswith(".mp3") or f.endswith(".json") and f != "manifest.json"):
            os.unlink(os.path.join(cache_dir, f))


def main():
    p = argparse.ArgumentParser(description="ElevenLabs dialogue generation with per-chunk cache.")
    p.add_argument("--input", "-i", required=True, help="Path to JSON dialogue file")
    p.add_argument("--output", "-o", default="dialogue.mp3", help="Output MP3 path")
    p.add_argument("--max-chars", "-m", type=int, default=MAX_CHARS_PER_CHUNK)
    p.add_argument("--force", action="store_true", help="Wipe cache and regenerate every chunk")
    p.add_argument("--regen", help="1-based chunk indices to force-regen (e.g. '3' or '3,7')")
    p.add_argument("--list-chunks", action="store_true", help="Print chunking plan and exit")
    p.add_argument("--no-concat", action="store_true", help="Generate chunks only; skip final concat")
    args = p.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        inputs = json.load(f)

    if not isinstance(inputs, list):
        print("ERROR: input JSON must be an array")
        sys.exit(1)

    chunks, starts = split_into_chunks(inputs, args.max_chars)
    total_chars = sum(len(i["text"]) for i in inputs)
    print(f"Plan: {len(inputs)} lines, {total_chars} chars, {len(chunks)} chunks")

    if args.list_chunks:
        for i, (chunk, start) in enumerate(zip(chunks, starts), 1):
            end = start + len(chunk) - 1
            h = chunk_hash(chunk)[:12]
            n_chars = sum(len(x["text"]) for x in chunk)
            print(f"  Chunk {i:2d}: lines {start:3d}-{end:3d} ({len(chunk):3d} lines, {n_chars:4d} chars) hash={h}")
        return

    cache_dir = cache_dir_for(args.output)
    os.makedirs(cache_dir, exist_ok=True)

    if args.force:
        for f in os.listdir(cache_dir):
            if f.endswith(".mp3") or f == "manifest.json":
                os.unlink(os.path.join(cache_dir, f))

    regen_set = set()
    if args.regen:
        try:
            regen_set = {int(x.strip()) for x in args.regen.split(",")}
        except ValueError:
            print("ERROR: --regen expects comma-separated integers")
            sys.exit(1)
        bad = [i for i in regen_set if i < 1 or i > len(chunks)]
        if bad:
            print(f"ERROR: --regen indices out of range (have {len(chunks)} chunks): {bad}")
            sys.exit(1)

    client = None
    records = []
    files_kept = []
    for i, (chunk, start) in enumerate(zip(chunks, starts), 1):
        h = chunk_hash(chunk)
        fname = f"chunk_{h[:12]}.mp3"
        path = os.path.join(cache_dir, fname)
        if i in regen_set and os.path.exists(path):
            os.unlink(path)
        chars = sum(len(x["text"]) for x in chunk)
        if os.path.exists(path):
            print(f"  Chunk {i:2d}/{len(chunks)}: CACHED   ({chars:4d} chars, {len(chunk):3d} lines) {fname}")
        else:
            print(f"  Chunk {i:2d}/{len(chunks)}: generating ({chars} chars, {len(chunk)} lines)...")
            if client is None:
                client = get_client()
            audio = generate_chunk(client, chunk)
            if audio is None:
                print(f"ERROR: chunk {i} failed")
                sys.exit(1)
            with open(path, "wb") as f:
                f.write(audio)
        records.append({
            "index": i,
            "line_start": start,
            "line_end": start + len(chunk) - 1,
            "char_count": chars,
            "text_hash": h,
            "audio_file": fname,
        })
        files_kept.append(fname)

    manifest = {
        "input_file": os.path.abspath(args.input),
        "output_file": os.path.abspath(args.output),
        "max_chars": args.max_chars,
        "chunks": records,
    }
    with open(os.path.join(cache_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    prune_orphans(cache_dir, files_kept)

    if args.no_concat:
        print(f"Skipped final concat (--no-concat). Cache: {cache_dir}")
        return

    print(f"Concatenating {len(records)} chunks...")
    audio_files = [os.path.join(cache_dir, r["audio_file"]) for r in records]
    if not concatenate(audio_files, args.output):
        sys.exit(1)
    print(f"SUCCESS: {args.output}")


if __name__ == "__main__":
    main()
