#!/usr/bin/env python3
"""Offline self-test for the soundvibes pipeline.

Synthesises English, German and Russian speech with the macOS `say` command,
pushes it through the *real* SpeechEndpointer / Transcriber / TranscriptWriter,
and checks that each phrase comes back in the right language. Nothing here
touches a microphone, so it is safe to run on a build machine.

    ./.venv/bin/python selftest.py
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
)

CASES = [
    ("en", "Samantha", "The quick brown fox jumps over the lazy dog every morning."),
    ("de", "Anna", "Guten Tag, dies ist ein deutscher Testsatz für die Spracherkennung."),
    ("ru", "Milena", "Добрый день, это тестовое предложение для распознавания речи."),
]


def synthesize(voice: str, phrase: str, destination: Path) -> Path:
    """Render `phrase` to a 16 kHz mono WAV using macOS `say` + ffmpeg."""
    aiff = destination.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), phrase], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
         "-ac", "1", "-ar", str(SAMPLE_RATE), str(destination)],
        check=True,
    )
    return destination


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == SAMPLE_RATE, "expected 16 kHz"
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def endpoint(audio: np.ndarray) -> list[np.ndarray]:
    """Run the audio through the real endpointer, with silence padding either side."""
    endpointer = SpeechEndpointer(silence_seconds=0.7, min_speech_seconds=0.4, max_speech_seconds=20.0)
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


def main() -> int:
    if sys.platform != "darwin" or shutil.which("say") is None:
        print("SKIP: this self-test needs macOS `say`.")
        return 0
    if shutil.which("ffmpeg") is None:
        print("SKIP: this self-test needs ffmpeg (brew install ffmpeg).")
        return 0

    languages = [code for code, _, _ in CASES]
    transcriber = Transcriber(
        model_size="small", languages=languages, device="cpu", compute_type="int8", beam_size=5
    )

    failures = 0
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        writer = TranscriptWriter(work / "transcript.txt", "text", True, languages)

        for expected_language, voice, phrase in CASES:
            wav = synthesize(voice, phrase, work / f"{expected_language}.wav")
            chunks = endpoint(read_wav(wav))

            print(f"\n--- {expected_language} ({voice}) ---")
            print(f"spoken:   {phrase}")
            if not chunks:
                print("FAIL: endpointer produced no utterance")
                failures += 1
                continue
            print(f"endpointed into {len(chunks)} utterance(s)")

            transcribed_languages = []
            for chunk in chunks:
                line = transcriber.transcribe(
                    Utterance("SYS", chunk, dt.datetime.now())
                )
                if line is None:
                    continue
                transcribed_languages.append(line.language)
                print(f"written:  {writer.write(line)}")

            if expected_language in transcribed_languages:
                print(f"OK: detected {expected_language}")
            else:
                print(f"FAIL: expected {expected_language}, got {transcribed_languages}")
                failures += 1

        writer.close()

        main_transcript = (work / "transcript.txt").read_text(encoding="utf-8")
        print("\n--- transcript.txt ---")
        print(main_transcript.strip())
        for code in languages:
            per_language = work / f"transcript.{code}.txt"
            if not per_language.exists():
                print(f"FAIL: missing {per_language.name}")
                failures += 1

    print("\nSELFTEST PASSED" if failures == 0 else f"\nSELFTEST FAILED ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
