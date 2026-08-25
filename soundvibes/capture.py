"""Turning a device's audio into 16 kHz mono frames, and the thread that does it.

The preprocessing and framing are plain objects with no device dependency, so
the fiddly parts (channel mixing, resampling, frame boundaries) are unit-tested
without any audio hardware.
"""
from __future__ import annotations

import queue
import sys
import threading
from typing import Optional

import numpy as np

from .constants import FRAME_SAMPLES, SAMPLE_RATE
from .devices import AudioBackend, DeviceInfo
from .endpointing import SpeechEndpointer
from .models import Utterance

#: raw blocks buffered per source before we start dropping audio
MAX_QUEUED_BLOCKS = 256
#: capture callback size, as a fraction of a second
BLOCK_SECONDS = 0.05


class AudioPreprocessor:
    """Device audio in, mono float32 at the whisper rate out."""

    def __init__(self, source_rate: int, target_rate: int = SAMPLE_RATE,
                 gain: float = 1.0, resample_quality: str = "HQ") -> None:
        self._source_rate = source_rate
        self._target_rate = target_rate
        self._gain = gain
        self._resample_quality = resample_quality

    def process(self, block: np.ndarray) -> np.ndarray:
        mono = block.mean(axis=1) if block.ndim > 1 else block
        if self._gain != 1.0:
            mono = mono * self._gain
        if self._source_rate != self._target_rate:
            import soxr  # noqa: PLC0415 - deferred so import soundvibes stays cheap

            mono = soxr.resample(mono, self._source_rate, self._target_rate,
                                 quality=self._resample_quality)
        return mono.astype(np.float32, copy=False)


class FrameSplitter:
    """Cuts a stream into fixed-size frames, carrying the remainder forward.

    Without the carry, every block boundary would drop up to one frame of audio.
    """

    def __init__(self, frame_samples: int = FRAME_SAMPLES) -> None:
        self._frame_samples = frame_samples
        self._residue = np.zeros(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list[np.ndarray]:
        combined = np.concatenate([self._residue, samples])
        usable = len(combined) - (len(combined) % self._frame_samples)
        self._residue = combined[usable:]
        return [combined[start:start + self._frame_samples]
                for start in range(0, usable, self._frame_samples)]


class AudioSource(threading.Thread):
    """Captures one device and publishes endpointed utterances onto a queue."""

    def __init__(
        self,
        label: str,
        device: DeviceInfo,
        backend: AudioBackend,
        endpointer: SpeechEndpointer,
        utterances: "queue.Queue[Utterance]",
        stop_event: threading.Event,
        gain: float = 1.0,
    ) -> None:
        super().__init__(name=f"capture-{label}", daemon=True)
        self.label = label
        self.device = device
        self.failure: Optional[Exception] = None

        self._backend = backend
        self._endpointer = endpointer
        self._utterances = utterances
        self._stop_event = stop_event
        self._preprocessor = AudioPreprocessor(source_rate=device.sample_rate, gain=gain)
        self._splitter = FrameSplitter()
        self._blocks: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)

    @property
    def device_name(self) -> str:
        return self.device.name

    def run(self) -> None:
        try:
            stream = self._backend.open_input_stream(
                device=self.device.index,
                channels=self.device.channels,
                samplerate=self.device.sample_rate,
                dtype="float32",
                blocksize=int(self.device.sample_rate * BLOCK_SECONDS),
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
        except Exception as error:  # noqa: BLE001 - a dead thread must not hang the app
            self.failure = error
            print(f"[{self.label}] capture stopped: {error}\n"
                  f"[{self.label}] device was {self.device.name!r}", file=sys.stderr)

    def _on_audio(self, indata, _frames, _time_info, status) -> None:
        if status:
            print(f"[{self.label}] audio status: {status}", file=sys.stderr)
        try:
            self._blocks.put_nowait(indata.copy())
        except queue.Full:
            pass  # transcription is behind; dropping raw audio beats unbounded RAM

    def _consume(self, block: np.ndarray) -> None:
        for frame in self._splitter.push(self._preprocessor.process(block)):
            self._emit(self._endpointer.push(frame))

    def _emit(self, finished) -> None:
        if finished is None:
            return
        audio, started_at = finished
        self._utterances.put(Utterance(self.label, audio, started_at))
