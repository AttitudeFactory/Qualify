"""Builds the voice experiment's recordings from Google's crowdsourced Colombian Spanish
corpus (OpenSLR 72, CC BY-SA 4.0, https://www.openslr.org/72/), read through the Hugging
Face datasets-server so only the clips used are downloaded (about 30 MB).

One clip is a single read sentence of ~5 s, too short for «Tu voz», so each recording is
the first 10 sentences of one speaker joined with half a second of silence (45-60 s), and
its reference is those sentences' human transcripts in the same order. The three women
and three men with the most clips are used. The WAVs go to `audio/` (git-ignored); the
transcripts are already in `cases.json`, so this only has to be run once per machine:

    just eval-voz-audio

Attribution (CC BY-SA 4.0): Guevara-Rukoz et al., «Crowdsourcing Latin American Spanish
for Low-Resource Text-to-Speech», LREC 2020.
"""

from __future__ import annotations

import collections
import io
import json
import sys
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DATASET = "ylacombe/google-colombian-spanish"
API = "https://datasets-server.huggingface.co/rows"
SPLITS = {"female": 2369, "male": 2534}
SPEAKERS_PER_SPLIT = 3
CLIPS_PER_RECORDING = 10
GAP_SECONDS = 0.5


def _get(url: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 — fixed host
                return response.read()
        except OSError:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not download {url.split('?')[0]}")


def _rows(config: str, total: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in range(0, total, 100):
        url = f"{API}?dataset={DATASET}&config={config}&split=train&offset={offset}&length=100"
        rows += [r["row"] for r in json.loads(_get(url))["rows"]]
    return rows


def build(config: str, speaker: str, rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """One speaker's clips joined into one WAV; returns its case for `cases.json`."""
    frames: list[bytes] = []
    texts: list[str] = []
    params: tuple[int, int, int] | None = None
    for row in rows[:CLIPS_PER_RECORDING]:
        with wave.open(io.BytesIO(_get(row["audio"][0]["src"]))) as clip:
            shape = (clip.getnchannels(), clip.getsampwidth(), clip.getframerate())
            params = params or shape
            if shape != params:
                continue
            frames.append(clip.readframes(clip.getnframes()))
            texts.append(row["text"].strip())
    assert params is not None
    channels, width, rate = params
    silence = b"\x00" * int(rate * GAP_SECONDS) * width * channels
    case_id = f"colombia-{config}-{speaker}"
    with wave.open(str(out / f"{case_id}.wav"), "wb") as joined:
        joined.setnchannels(channels)
        joined.setsampwidth(width)
        joined.setframerate(rate)
        joined.writeframes(silence.join(frames))
    return {
        "id": case_id,
        "audio": f"audio/{case_id}.wav",
        "reference": " ".join(texts),
        "language": "es",
    }


def main() -> int:
    out = HERE / "audio"
    out.mkdir(exist_ok=True)
    cases = []
    for config, total in SPLITS.items():
        by_speaker: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for row in _rows(config, total):
            by_speaker[str(row["speaker_id"])].append(row)
        for speaker in sorted(by_speaker, key=lambda s: -len(by_speaker[s]))[:SPEAKERS_PER_SPLIT]:
            cases.append(build(config, speaker, by_speaker[speaker], out))
            print(f"audio/{cases[-1]['id']}.wav", flush=True)
    path = HERE / "cases.json"
    known = json.loads(path.read_text(encoding="utf-8"))
    ids = {c["id"] for c in known["cases"]}
    missing = [c["id"] for c in cases if c["id"] not in ids]
    if missing:
        print(f"Not in cases.json yet (add them with their reference): {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
