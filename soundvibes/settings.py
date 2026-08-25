"""Immutable settings objects.

Frozen on purpose: they are built once from the command line and then read from
several threads. Nothing downstream should be able to reconfigure the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class EndpointerSettings:
    silence_seconds: float = 0.7
    min_speech_seconds: float = 0.4
    max_speech_seconds: float = 20.0
    preroll_seconds: float = 0.32
    sensitivity: float = 3.0
    absolute_floor: float = 0.004


@dataclass(frozen=True)
class TranscriptionSettings:
    languages: tuple[str, ...] = ("en", "de", "ru")
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 5


@dataclass(frozen=True)
class OutputSettings:
    path: Path = Path("transcripts/transcript.txt")
    format_name: str = "text"
    split_by_language: bool = False
    quiet: bool = False


@dataclass(frozen=True)
class CaptureSettings:
    capture_microphone: bool = True
    capture_system: bool = True
    input_device: Optional[str] = None
    system_device: Optional[str] = None


@dataclass(frozen=True)
class Settings:
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    endpointer: EndpointerSettings = field(default_factory=EndpointerSettings)
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
