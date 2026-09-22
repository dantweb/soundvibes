"""Immutable settings objects.

Frozen on purpose: they are built once from the command line and then read from
several threads. Nothing downstream should be able to reconfigure the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import CONFIG


@dataclass(frozen=True)
class EndpointerSettings:
    silence_seconds: float = CONFIG.endpointer.silence_seconds
    min_speech_seconds: float = CONFIG.endpointer.min_speech_seconds
    max_speech_seconds: float = CONFIG.endpointer.max_speech_seconds
    preroll_seconds: float = CONFIG.endpointer.preroll_seconds
    sensitivity: float = CONFIG.endpointer.sensitivity
    absolute_floor: float = CONFIG.endpointer.absolute_floor


@dataclass(frozen=True)
class TranscriptionSettings:
    languages: tuple[str, ...] = tuple(CONFIG.transcription.languages)
    model_size: str = CONFIG.transcription.model_size
    device: str = CONFIG.transcription.device
    compute_type: str = CONFIG.transcription.compute_type
    beam_size: int = CONFIG.transcription.beam_size


@dataclass(frozen=True)
class TranslationSettings:
    """Off by default: nothing is translated unless target languages are asked for."""

    targets: tuple[str, ...] = tuple(CONFIG.translation.targets)
    backend: str = CONFIG.translation.backend

    @property
    def enabled(self) -> bool:
        return bool(self.targets)


@dataclass(frozen=True)
class OutputSettings:
    path: Path = Path(CONFIG.output.path)
    format_name: str = CONFIG.output.format
    split_by_language: bool = CONFIG.output.split_by_language
    quiet: bool = CONFIG.output.quiet


@dataclass(frozen=True)
class CaptureSettings:
    capture_microphone: bool = True
    capture_system: bool = True
    input_device: str | None = None
    system_device: str | None = None


@dataclass(frozen=True)
class Settings:
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    endpointer: EndpointerSettings = field(default_factory=EndpointerSettings)
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
