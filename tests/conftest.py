"""Shared fakes. Every seam the real program depends on has a test double here,
so the whole suite runs with no microphone, no model download and no ffmpeg.
"""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from soundvibes.constants import SAMPLE_RATE
from soundvibes.models import Utterance
from soundvibes.transcription import EngineResult, Segment


class FakeAudioBackend:
    """Stands in for sounddevice: a fixed device table, no hardware."""

    def __init__(self, devices=None, default_input=1):
        self._devices = devices if devices is not None else [
            {"name": "Built-in Microphone", "max_input_channels": 1,
             "max_output_channels": 0, "default_samplerate": 48000},
            {"name": "MacBook Pro Microphone", "max_input_channels": 1,
             "max_output_channels": 0, "default_samplerate": 48000},
            {"name": "BlackHole 2ch", "max_input_channels": 2,
             "max_output_channels": 2, "default_samplerate": 48000},
            {"name": "External Headphones", "max_input_channels": 0,
             "max_output_channels": 2, "default_samplerate": 48000},
        ]
        self._default_input = default_input
        self.opened_streams = []

    def query_devices(self):
        return list(self._devices)

    def device_info(self, index):
        return dict(self._devices[index])

    def default_input_index(self):
        return self._default_input

    def open_input_stream(self, **kwargs):
        self.opened_streams.append(kwargs)
        return FakeStream()


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


class FakeEngine:
    """Stands in for faster-whisper. Scripted results, records every call."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def transcribe(self, audio, language, beam_size):
        self.calls.append({"language": language, "beam_size": beam_size,
                           "samples": len(audio)})
        if self.results:
            return self.results.pop(0)
        return EngineResult(segments=[], language="en", language_probability=0.0,
                            all_language_probabilities=[])


def make_result(text="hello there", language="en", probability=0.9,
                no_speech=0.01, average_logprob=-0.2, all_probabilities=None):
    return EngineResult(
        segments=[Segment(text=text, no_speech_probability=no_speech,
                          average_logprob=average_logprob)],
        language=language,
        language_probability=probability,
        all_language_probabilities=all_probabilities or [],
    )


@pytest.fixture
def backend():
    return FakeAudioBackend()


@pytest.fixture
def utterance():
    return Utterance(source="MIC", audio=np.zeros(SAMPLE_RATE, dtype=np.float32),
                     started_at=dt.datetime(2026, 8, 25, 13, 41, 39))


def tone(seconds, amplitude=0.3, rate=SAMPLE_RATE, frequency=220.0):
    samples = np.arange(int(seconds * rate), dtype=np.float32)
    return (amplitude * np.sin(2 * np.pi * frequency * samples / rate)).astype(np.float32)


def silence(seconds, rate=SAMPLE_RATE):
    return np.zeros(int(seconds * rate), dtype=np.float32)
