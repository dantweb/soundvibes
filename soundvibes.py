#!/usr/bin/env python3
"""soundvibes - live speech-to-text for microphone input AND system audio output.

Captures two audio sources at once:

  * MIC - what you say (any input device, default: system default input)
  * SYS - what your computer plays (needs a loopback device such as BlackHole)

Every utterance is detected by an energy-based endpointer, transcribed with
faster-whisper, and appended to a transcript file while the program runs.
Language is auto-detected per utterance and constrained to the languages you
allow - by default English, German and Russian.

Usage:
    python soundvibes.py --list-devices
    python soundvibes.py -o transcript.txt
    python soundvibes.py --languages en,de,ru --model small --split-by-language

Stop with Ctrl-C; the transcript is flushed after every line, so it is always
complete even if the process is killed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import sounddevice as sd
import soxr

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SAMPLE_RATE = 16_000  # what whisper wants
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

SOURCE_MIC = "MIC"
SOURCE_SYS = "SYS"

# Substrings that identify a loopback / virtual output-capture device.
LOOPBACK_HINTS = (
    "blackhole",
    "soundflower",
    "loopback",
    "vb-cable",
    "vb cable",
    "virtual audio",
    "aggregate",
    "multi-output",
    "multi output",
    "stereo mix",
    "monitor of",
)

# Whisper happily invents these when handed near-silence or music.
HALLUCINATION_BLOCKLIST = {
    "thank you.",
    "thanks for watching!",
    "you",
    "bye.",
    "untertitel von stephanie geiges",
    "untertitelung des zdf, 2020",
    "продолжение следует...",
    "субтитры сделал dimatorzok",
    "редактор субтитров а.синецкая корректор а.егорова",
    "amara.org",
}


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #


@dataclass
class Utterance:
    """One endpointed chunk of speech, ready to be transcribed."""

    source: str
    audio: np.ndarray  # float32, mono, 16 kHz
    started_at: dt.datetime

    @property
    def duration_seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE


@dataclass
class TranscriptLine:
    source: str
    language: str
    text: str
    started_at: dt.datetime
    duration_seconds: float
    language_probability: float


# --------------------------------------------------------------------------- #
# Device discovery
# --------------------------------------------------------------------------- #


def list_devices() -> None:
    """Print every audio device, marking the ones we can capture from."""
    devices = sd.query_devices()
    default_input, _ = sd.default.device
    print(f"{'idx':>4}  {'in':>3} {'out':>3}  {'rate':>7}  name")
    print("-" * 78)
    for index, device in enumerate(devices):
        if device["max_input_channels"] < 1:
            continue
        marks = []
        if index == default_input:
            marks.append("default-input")
        if is_loopback_device(device["name"]):
            marks.append("loopback -> usable as SYS")
        suffix = f"   [{', '.join(marks)}]" if marks else ""
        print(
            f"{index:>4}  {device['max_input_channels']:>3} "
            f"{device['max_output_channels']:>3}  "
            f"{int(device['default_samplerate']):>7}  {device['name']}{suffix}"
        )


def is_loopback_device(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in LOOPBACK_HINTS)


def resolve_device(spec: Optional[str]) -> Optional[int]:
    """Turn a device index or (partial, case-insensitive) name into an index."""
    if spec is None:
        return None
    spec = spec.strip()
    if spec.isdigit():
        return int(spec)
    lowered = spec.lower()
    matches = [
        index
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0 and lowered in device["name"].lower()
    ]
    if not matches:
        raise SystemExit(
            f"No input-capable device matches {spec!r}. "
            f"Run with --list-devices to see the options."
        )
    if len(matches) > 1:
        names = ", ".join(f"{i}:{sd.query_devices(i)['name']}" for i in matches)
        raise SystemExit(f"{spec!r} is ambiguous, matches: {names}")
    return matches[0]


def autodetect_loopback_device() -> Optional[int]:
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0 and is_loopback_device(device["name"]):
            return index
    return None


LOOPBACK_HELP = """\
No loopback device found, so system audio (SYS) will NOT be captured.

macOS cannot record its own output without a virtual audio driver. To enable it:

    brew install blackhole-2ch          # then log out / restart audio

Then either
    * pick "BlackHole 2ch" as your system output (you stop hearing the sound), or
    * open "Audio MIDI Setup" -> + -> "Create Multi-Output Device", tick both your
      speakers and BlackHole 2ch, and select that as the system output
      (you keep hearing the sound - recommended).

soundvibes picks the loopback input up automatically on the next run, or pass it
explicitly with --system-device "BlackHole".
"""


# --------------------------------------------------------------------------- #
# Endpointing (energy VAD)
# --------------------------------------------------------------------------- #


class SpeechEndpointer:
    """Splits a continuous stream into utterances using adaptive energy gating.

    Keeps a running estimate of the noise floor so it works both in a quiet room
    and on a noisy line, without any model or threshold tuning by the user.
    """

    def __init__(
        self,
        silence_seconds: float,
        min_speech_seconds: float,
        max_speech_seconds: float,
        preroll_seconds: float = 0.32,
        sensitivity: float = 3.0,
        absolute_floor: float = 0.004,
    ) -> None:
        self._silence_frames = max(1, int(silence_seconds * 1000 / FRAME_MS))
        self._min_speech_samples = int(min_speech_seconds * SAMPLE_RATE)
        self._max_speech_samples = int(max_speech_seconds * SAMPLE_RATE)
        self._preroll_frames = max(1, int(preroll_seconds * 1000 / FRAME_MS))
        self._sensitivity = sensitivity
        self._absolute_floor = absolute_floor

        self._noise_floor = 0.0
        self._noise_initialised = False
        self._preroll: list[np.ndarray] = []
        self._speech: list[np.ndarray] = []
        self._trailing_silence = 0
        self._leading_speech = 0
        self._started_at: Optional[dt.datetime] = None

    def push(self, frame: np.ndarray) -> Optional[tuple[np.ndarray, dt.datetime]]:
        """Feed exactly one frame; return a finished utterance when one ends."""
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))

        if not self._noise_initialised:
            self._noise_floor = rms
            self._noise_initialised = True

        threshold = max(self._noise_floor * self._sensitivity, self._absolute_floor)
        is_speech = rms > threshold

        if not self._speech:
            # Idle: adapt the noise floor and keep a short pre-roll so we do not
            # clip the first consonant of a word.
            if is_speech:
                self._leading_speech += 1
            else:
                self._leading_speech = 0
                self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms

            self._preroll.append(frame)
            if len(self._preroll) > self._preroll_frames:
                self._preroll.pop(0)

            if self._leading_speech >= 2:
                self._speech = list(self._preroll)
                self._preroll = []
                self._trailing_silence = 0
                self._started_at = dt.datetime.now()
            return None

        # Inside an utterance.
        self._speech.append(frame)
        self._trailing_silence = 0 if is_speech else self._trailing_silence + 1

        collected = sum(len(chunk) for chunk in self._speech)
        ended = self._trailing_silence >= self._silence_frames
        overlong = collected >= self._max_speech_samples
        if not (ended or overlong):
            return None
        return self._finish(discard_short=ended)

    def flush(self) -> Optional[tuple[np.ndarray, dt.datetime]]:
        """Close an utterance still in progress (called on shutdown)."""
        return self._finish(discard_short=True) if self._speech else None

    def _finish(self, discard_short: bool) -> Optional[tuple[np.ndarray, dt.datetime]]:
        audio = np.concatenate(self._speech)
        started_at = self._started_at or dt.datetime.now()
        self._speech = []
        self._leading_speech = 0
        self._trailing_silence = 0
        self._started_at = None
        if discard_short and len(audio) < self._min_speech_samples:
            return None
        return audio, started_at


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #


class AudioSource(threading.Thread):
    """Captures one device, resamples to 16 kHz mono, and endpoints utterances."""

    def __init__(
        self,
        label: str,
        device_index: Optional[int],
        utterances: "queue.Queue[Utterance]",
        stop_event: threading.Event,
        endpointer: SpeechEndpointer,
        gain: float = 1.0,
    ) -> None:
        super().__init__(name=f"capture-{label}", daemon=True)
        self.label = label
        self.failure: Optional[Exception] = None
        self._device_index = device_index
        self._utterances = utterances
        self._stop_event = stop_event
        self._endpointer = endpointer
        self._gain = gain
        self._blocks: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=256)
        self._residue = np.zeros(0, dtype=np.float32)

        info = sd.query_devices(device_index, "input")
        self.device_name: str = info["name"]
        self._channels = min(2, int(info["max_input_channels"]))
        self._device_rate = int(info["default_samplerate"])

    def _on_audio(self, indata, _frames, _time_info, status) -> None:
        if status:
            print(f"[{self.label}] audio status: {status}", file=sys.stderr)
        try:
            self._blocks.put_nowait(indata.copy())
        except queue.Full:
            pass  # transcription is behind; dropping raw audio beats unbounded RAM

    def run(self) -> None:
        try:
            stream = sd.InputStream(
                device=self._device_index,
                channels=self._channels,
                samplerate=self._device_rate,
                dtype="float32",
                blocksize=int(self._device_rate * 0.05),
                callback=self._on_audio,
            )
            with stream:
                while not self._stop_event.is_set():
                    try:
                        block = self._blocks.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    self._consume(block)
            self._emit(self._endpointer.flush())
        except Exception as error:
            # A dead capture thread must not leave the main loop waiting forever.
            self.failure = error
            print(
                f"[{self.label}] capture stopped: {error}\n"
                f"[{self.label}] device was {self.device_name!r}",
                file=sys.stderr,
            )

    def _consume(self, block: np.ndarray) -> None:
        mono = block.mean(axis=1) if block.ndim > 1 else block
        if self._gain != 1.0:
            mono = mono * self._gain
        if self._device_rate != SAMPLE_RATE:
            mono = soxr.resample(mono, self._device_rate, SAMPLE_RATE, quality="HQ")

        samples = np.concatenate([self._residue, mono.astype(np.float32, copy=False)])
        usable = len(samples) - (len(samples) % FRAME_SAMPLES)
        self._residue = samples[usable:]
        for start in range(0, usable, FRAME_SAMPLES):
            self._emit(self._endpointer.push(samples[start : start + FRAME_SAMPLES]))

    def _emit(self, finished: Optional[tuple[np.ndarray, dt.datetime]]) -> None:
        if finished is None:
            return
        audio, started_at = finished
        self._utterances.put(Utterance(self.label, audio, started_at))


# --------------------------------------------------------------------------- #
# Transcription
# --------------------------------------------------------------------------- #


class Transcriber:
    """Wraps faster-whisper and constrains detection to the allowed languages."""

    def __init__(
        self,
        model_size: str,
        languages: list[str],
        device: str,
        compute_type: str,
        beam_size: int,
    ) -> None:
        from faster_whisper import WhisperModel  # imported late: slow + optional

        print(f"Loading whisper model {model_size!r} ({device}/{compute_type})...")
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._languages = languages
        self._beam_size = beam_size
        print("Model ready.")

    def transcribe(self, utterance: Utterance) -> Optional[TranscriptLine]:
        segments, info = self._model.transcribe(
            utterance.audio,
            language=self._languages[0] if len(self._languages) == 1 else None,
            beam_size=self._beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        language = info.language
        probability = info.language_probability

        # Whisper can detect any of ~100 languages; force it into the allowed set.
        if len(self._languages) > 1 and language not in self._languages:
            best, best_probability = self._best_allowed(info.all_language_probs)
            if best is not None:
                segments, info = self._model.transcribe(
                    utterance.audio,
                    language=best,
                    beam_size=self._beam_size,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                language, probability = best, best_probability

        text = self._collect(segments)
        if not text:
            return None
        return TranscriptLine(
            source=utterance.source,
            language=language,
            text=text,
            started_at=utterance.started_at,
            duration_seconds=utterance.duration_seconds,
            language_probability=probability,
        )

    def _best_allowed(self, all_probs) -> tuple[Optional[str], float]:
        if not all_probs:
            return None, 0.0
        allowed = [(code, p) for code, p in all_probs if code in self._languages]
        if not allowed:
            return None, 0.0
        return max(allowed, key=lambda item: item[1])

    @staticmethod
    def _collect(segments: Iterable) -> str:
        parts = []
        for segment in segments:
            if segment.no_speech_prob > 0.6 or segment.avg_logprob < -1.0:
                continue
            piece = segment.text.strip()
            if piece and piece.lower().strip(" .!?…") not in HALLUCINATION_BLOCKLIST:
                parts.append(piece)
        text = " ".join(parts).strip()
        return "" if text.lower() in HALLUCINATION_BLOCKLIST else text


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


class TranscriptWriter:
    """Appends transcript lines to disk, flushing after each one."""

    def __init__(
        self,
        path: Path,
        output_format: str,
        split_by_language: bool,
        languages: list[str],
    ) -> None:
        self._format = output_format
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._main = path.open("a", encoding="utf-8")
        self._per_language: dict[str, object] = {}
        if split_by_language:
            for code in languages:
                language_path = path.with_name(f"{path.stem}.{code}{path.suffix}")
                self._per_language[code] = language_path.open("a", encoding="utf-8")
        self._write_header()

    def _write_header(self) -> None:
        if self._format != "text":
            return
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for handle in [self._main, *self._per_language.values()]:
            handle.write(f"\n===== soundvibes session started {stamp} =====\n")
            handle.flush()

    def write(self, line: TranscriptLine) -> str:
        rendered = self._render(line)
        self._main.write(rendered + "\n")
        self._main.flush()
        handle = self._per_language.get(line.language)
        if handle is not None:
            handle.write(rendered + "\n")
            handle.flush()
        return rendered

    def _render(self, line: TranscriptLine) -> str:
        if self._format == "jsonl":
            return json.dumps(
                {
                    "timestamp": line.started_at.isoformat(timespec="seconds"),
                    "source": line.source,
                    "language": line.language,
                    "language_probability": round(line.language_probability, 3),
                    "duration_seconds": round(line.duration_seconds, 2),
                    "text": line.text,
                },
                ensure_ascii=False,
            )
        clock = line.started_at.strftime("%H:%M:%S")
        return f"[{clock}] [{line.source}] [{line.language}] {line.text}"

    def close(self) -> None:
        for handle in [self._main, *self._per_language.values()]:
            handle.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="soundvibes",
        description="Live speech-to-text of microphone input and system audio output.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--list-devices", action="store_true", help="show audio devices and exit")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("transcripts/transcript.txt"),
        help="transcript file (appended to, never truncated)",
    )
    parser.add_argument(
        "--format", choices=["text", "jsonl"], default="text", help="transcript line format"
    )
    parser.add_argument(
        "--split-by-language",
        action="store_true",
        help="also write transcript.en.txt / transcript.de.txt / transcript.ru.txt",
    )
    parser.add_argument(
        "--languages",
        default="en,de,ru",
        help="comma-separated whisper language codes to allow (auto-detected per utterance)",
    )
    parser.add_argument("--model", default="small", help="whisper model: tiny/base/small/medium/large-v3")
    parser.add_argument("--device", default="cpu", help="compute device for whisper: cpu or cuda")
    parser.add_argument("--compute-type", default="int8", help="ctranslate2 compute type")
    parser.add_argument("--beam-size", type=int, default=5, help="whisper beam size")
    parser.add_argument("--input-device", help="index or name of the microphone device")
    parser.add_argument("--system-device", help="index or name of the loopback device for system audio")
    parser.add_argument("--no-mic", action="store_true", help="do not capture the microphone")
    parser.add_argument("--no-system", action="store_true", help="do not capture system output")
    parser.add_argument("--silence", type=float, default=0.7, help="seconds of silence that end an utterance")
    parser.add_argument("--min-speech", type=float, default=0.4, help="shorter utterances are discarded")
    parser.add_argument("--max-speech", type=float, default=20.0, help="force-split utterances longer than this")
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=3.0,
        help="speech threshold as a multiple of the noise floor (lower = more sensitive)",
    )
    parser.add_argument("--quiet", action="store_true", help="do not echo transcript lines to the console")
    return parser.parse_args(argv)


def build_sources(
    args: argparse.Namespace,
    utterances: "queue.Queue[Utterance]",
    stop_event: threading.Event,
) -> list[AudioSource]:
    def endpointer() -> SpeechEndpointer:
        return SpeechEndpointer(
            silence_seconds=args.silence,
            min_speech_seconds=args.min_speech,
            max_speech_seconds=args.max_speech,
            sensitivity=args.sensitivity,
        )

    sources: list[AudioSource] = []

    if not args.no_mic:
        sources.append(
            AudioSource(
                SOURCE_MIC, resolve_device(args.input_device), utterances, stop_event, endpointer()
            )
        )

    if not args.no_system:
        system_index = resolve_device(args.system_device)
        if system_index is None:
            system_index = autodetect_loopback_device()
        if system_index is None:
            print(LOOPBACK_HELP, file=sys.stderr)
        else:
            sources.append(
                AudioSource(SOURCE_SYS, system_index, utterances, stop_event, endpointer())
            )

    if not sources:
        raise SystemExit("Nothing to capture: both --no-mic and --no-system (or no devices).")
    return sources


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.list_devices:
        list_devices()
        return 0

    languages = [code.strip() for code in args.languages.split(",") if code.strip()]
    if not languages:
        raise SystemExit("--languages must list at least one language code.")

    utterances: "queue.Queue[Utterance]" = queue.Queue()
    stop_event = threading.Event()
    sources = build_sources(args, utterances, stop_event)

    transcriber = Transcriber(
        model_size=args.model,
        languages=languages,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
    )
    writer = TranscriptWriter(args.output, args.format, args.split_by_language, languages)

    def request_stop(*_args) -> None:
        if not stop_event.is_set():
            print("\nStopping - draining the queue, please wait...")
            stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    for source in sources:
        source.start()

    captured = ", ".join(f"{s.label}={s.device_name}" for s in sources)
    print(f"Listening on {captured}")
    print(f"Languages: {'/'.join(languages)}   Transcript: {args.output.resolve()}")
    print("Press Ctrl-C to stop.\n")

    lines_written = 0
    try:
        while True:
            try:
                utterance = utterances.get(timeout=0.25)
            except queue.Empty:
                if not any(source.is_alive() for source in sources):
                    if not stop_event.is_set():
                        print(
                            "All capture sources stopped, exiting. On macOS check "
                            "System Settings > Privacy & Security > Microphone.",
                            file=sys.stderr,
                        )
                    break
                continue

            line = transcriber.transcribe(utterance)
            if line is None:
                continue
            rendered = writer.write(line)
            lines_written += 1
            if not args.quiet:
                print(rendered, flush=True)
    finally:
        stop_event.set()
        for source in sources:
            source.join(timeout=2.0)
        # Anything endpointed during shutdown still deserves a transcript line.
        while not utterances.empty():
            line = transcriber.transcribe(utterances.get())
            if line is not None:
                rendered = writer.write(line)
                lines_written += 1
                if not args.quiet:
                    print(rendered, flush=True)
        writer.close()

    print(f"\nWrote {lines_written} transcript line(s) to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
