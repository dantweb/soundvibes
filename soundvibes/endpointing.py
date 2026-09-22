"""Energy-based utterance detection.

Keeps a running estimate of the noise floor so it works in a quiet room and on
a noisy line without the user tuning a threshold.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from .config import CONFIG
from .constants import FRAME_MS, SAMPLE_RATE

_DEFAULTS = CONFIG.endpointer

FinishedUtterance = tuple[np.ndarray, dt.datetime]


class SpeechEndpointer:
    """Splits a continuous frame stream into utterances."""

    #: consecutive loud frames before we call it speech
    ONSET_FRAMES = _DEFAULTS.onset_frames
    #: how fast the idle noise estimate follows the room
    NOISE_ADAPTION = _DEFAULTS.noise_adaption

    def __init__(
        self,
        silence_seconds: float = _DEFAULTS.silence_seconds,
        min_speech_seconds: float = _DEFAULTS.min_speech_seconds,
        max_speech_seconds: float = _DEFAULTS.max_speech_seconds,
        preroll_seconds: float = _DEFAULTS.preroll_seconds,
        sensitivity: float = _DEFAULTS.sensitivity,
        absolute_floor: float = _DEFAULTS.absolute_floor,
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
        self._voiced_samples = 0
        self._started_at: dt.datetime | None = None

    def push(self, frame: np.ndarray) -> FinishedUtterance | None:
        """Feed exactly one frame; return a finished utterance when one ends."""
        loudness = self._loudness(frame)
        if not self._noise_initialised:
            self._noise_floor = loudness
            self._noise_initialised = True

        is_speech = loudness > self._threshold()
        if not self._speech:
            self._observe_while_idle(frame, loudness, is_speech)
            return None
        return self._observe_while_speaking(frame, is_speech)

    def flush(self) -> FinishedUtterance | None:
        """Close an utterance still in progress (called on shutdown)."""
        return self._finish(discard_short=True) if self._speech else None

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _loudness(frame: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))

    def _threshold(self) -> float:
        return max(self._noise_floor * self._sensitivity, self._absolute_floor)

    def _observe_while_idle(self, frame: np.ndarray, loudness: float, is_speech: bool) -> None:
        """Adapt to the room and keep a pre-roll so no leading consonant is clipped."""
        if is_speech:
            self._leading_speech += 1
        else:
            self._leading_speech = 0
            self._noise_floor = (
                1 - self.NOISE_ADAPTION
            ) * self._noise_floor + self.NOISE_ADAPTION * loudness

        self._preroll.append(frame)
        if len(self._preroll) > self._preroll_frames:
            self._preroll.pop(0)

        if self._leading_speech >= self.ONSET_FRAMES:
            self._speech = list(self._preroll)
            self._preroll = []
            self._trailing_silence = 0
            self._voiced_samples = self._leading_speech * len(frame)
            self._started_at = dt.datetime.now()

    def _observe_while_speaking(
        self, frame: np.ndarray, is_speech: bool
    ) -> FinishedUtterance | None:
        self._speech.append(frame)
        if is_speech:
            self._voiced_samples += len(frame)
        self._trailing_silence = 0 if is_speech else self._trailing_silence + 1

        collected = sum(len(chunk) for chunk in self._speech)
        ended_on_silence = self._trailing_silence >= self._silence_frames
        overlong = collected >= self._max_speech_samples
        if not (ended_on_silence or overlong):
            return None
        # A forced split keeps its audio; only a silence-ended blip is discarded.
        return self._finish(discard_short=ended_on_silence)

    def _finish(self, discard_short: bool) -> FinishedUtterance | None:
        audio = np.concatenate(self._speech)
        started_at = self._started_at or dt.datetime.now()
        voiced_samples = self._voiced_samples
        self._speech = []
        self._leading_speech = 0
        self._trailing_silence = 0
        self._voiced_samples = 0
        self._started_at = None
        # Gate on how much of the buffer was actually speech. Measuring the
        # whole buffer made --min-speech unreachable, because the pre-roll and
        # the trailing silence that ends an utterance already exceed it.
        if discard_short and voiced_samples < self._min_speech_samples:
            return None
        return audio, started_at
