"""The two values that travel through the pipeline."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from .constants import SAMPLE_RATE


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
    """One transcribed utterance, ready to be formatted and written."""

    source: str
    language: str
    text: str
    started_at: dt.datetime
    duration_seconds: float
    language_probability: float
