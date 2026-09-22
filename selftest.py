#!/usr/bin/env python3
"""End-to-end self-test for the soundvibes pipeline.

Synthesises English, German and Russian speech with the platform's offline TTS
(`say` on macOS, `espeak-ng` on Linux), pushes it through the *real*
SpeechEndpointer / Transcriber / TranscriptWriter, and checks that each phrase
comes back in the right language. No microphone is involved, so it is safe to
run on a build machine.

    ./.venv/bin/python selftest.py

This is the integration check. The fast unit suite is `pytest tests/`, which
needs neither a model nor a TTS binary.
"""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from soundvibes import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    SpeechEndpointer,
    Transcriber,
    TranscriptWriter,
    Utterance,
    platform_for,
)

CASES = [
    ("en", "The quick brown fox jumps over the lazy dog every morning."),
    ("de", "Guten Tag, dies ist ein deutscher Testsatz für die Spracherkennung."),
    ("ru", "Добрый день, это тестовое предложение для распознавания речи."),
]


def synthesize(platform, language: str, phrase: str, destination: Path) -> Path:
    """Render `phrase` to a 16 kHz mono WAV using the platform's TTS + ffmpeg."""
    raw = destination.with_suffix(platform.synthesis_suffix)
    subprocess.run(platform.synthesis_command(phrase, str(raw), language), check=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            str(destination),
        ],
        check=True,
    )
    return destination


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == SAMPLE_RATE, "expected 16 kHz"
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def endpoint(audio: np.ndarray) -> list[np.ndarray]:
    """Run the audio through the real endpointer, padded with silence either side."""
    endpointer = SpeechEndpointer(
        silence_seconds=0.7, min_speech_seconds=0.4, max_speech_seconds=20.0
    )
    padding = np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1 s of digital silence
    padded = np.concatenate([padding, audio, padding])

    utterances = []
    usable = len(padded) - (len(padded) % FRAME_SAMPLES)
    for start in range(0, usable, FRAME_SAMPLES):
        finished = endpointer.push(padded[start : start + FRAME_SAMPLES])
        if finished is not None:
            utterances.append(finished[0])
    trailing = endpointer.flush()
    if trailing is not None:
        utterances.append(trailing[0])
    return utterances


def missing_tool(platform) -> str | None:
    if shutil.which(platform.synthesis_binary) is None:
        hint = "brew install espeak-ng" if platform.name != "macos" else "`say` ships with macOS"
        return f"needs {platform.synthesis_binary} ({hint})"
    if shutil.which("ffmpeg") is None:
        return "needs ffmpeg"
    return None


def main() -> int:
    platform = platform_for()
    unavailable = missing_tool(platform)
    if unavailable:
        print(f"SKIP: this self-test {unavailable}.")
        return 0

    print(f"Platform: {platform.name} (TTS: {platform.synthesis_binary})")
    languages = [code for code, _ in CASES]
    transcriber = Transcriber(
        model_size="small", languages=languages, device="cpu", compute_type="int8", beam_size=5
    )

    failures = 0
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        writer = TranscriptWriter(work / "transcript.txt", "text", True, languages)

        for expected_language, phrase in CASES:
            wav = synthesize(platform, expected_language, phrase, work / f"{expected_language}.wav")
            chunks = endpoint(read_wav(wav))

            print(f"\n--- {expected_language} ---")
            print(f"spoken:   {phrase}")
            if not chunks:
                print("FAIL: endpointer produced no utterance")
                failures += 1
                continue
            print(f"endpointed into {len(chunks)} utterance(s)")

            detected = []
            for chunk in chunks:
                line = transcriber.transcribe(Utterance("SYS", chunk, dt.datetime.now()))
                if line is None:
                    continue
                detected.append(line.language)
                print(f"written:  {writer.write(line)}")

            if expected_language in detected:
                print(f"OK: detected {expected_language}")
            else:
                print(f"FAIL: expected {expected_language}, got {detected}")
                failures += 1

        writer.close()

        print("\n--- transcript.txt ---")
        print((work / "transcript.txt").read_text(encoding="utf-8").strip())
        for code in languages:
            if not (work / f"transcript.{code}.txt").exists():
                print(f"FAIL: missing transcript.{code}.txt")
                failures += 1

    print("\nSELFTEST PASSED" if failures == 0 else f"\nSELFTEST FAILED ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
