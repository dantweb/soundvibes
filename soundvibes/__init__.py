# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Daniil Tkachev
"""soundvibes - live speech-to-text for microphone input AND system audio output.

Captures two sources at once:

  * MIC - what you say (any input device, default: system default input)
  * SYS - what your computer plays (macOS: a loopback driver such as BlackHole;
          Linux: the ".monitor" source PulseAudio/PipeWire already exposes)

Every utterance is detected by an energy endpointer, transcribed with
faster-whisper, and appended to a transcript file while the program runs.
Language is auto-detected per utterance and constrained to the languages you
allow - by default English, German and Russian.

The names below are the stable public surface; everything else is free to move.
"""

from .capture import AudioPreprocessor, AudioSource, FrameSplitter
from .cli import build_settings, main, parse_args
from .constants import (
    FRAME_MS,
    FRAME_SAMPLES,
    SAMPLE_RATE,
    SOURCE_MIC,
    SOURCE_MICROPHONE,
    SOURCE_SYS,
    SOURCE_SYSTEM,
)
from .devices import DeviceRegistry, DeviceResolutionError, SoundDeviceBackend
from .endpointing import SpeechEndpointer
from .formatters import (
    JsonlFormatter,
    TextFormatter,
    available_formats,
    create_formatter,
    register_formatter,
)
from .models import TranscriptLine, Utterance
from .pipeline import TranscriptionPipeline
from .platforms import platform_for
from .settings import Settings
from .transcription import (
    EngineResult,
    HallucinationFilter,
    Segment,
    TextAssembler,
    Transcriber,
    TranscriptionEngine,
    TranscriptionService,
    WhisperEngine,
)
from .translation import (
    ArgosTranslator,
    CachingTranslator,
    ClaudeTranslator,
    IdentityTranslator,
    TranslationError,
    Translator,
    available_translators,
    create_translator,
    normalise_language,
    register_translator,
)
from .writer import CompositeWriter, TranscriptWriter, TranslationWriter

__all__ = [
    "AudioPreprocessor",
    "AudioSource",
    "FrameSplitter",
    "DeviceRegistry",
    "DeviceResolutionError",
    "SoundDeviceBackend",
    "EngineResult",
    "HallucinationFilter",
    "Segment",
    "TextAssembler",
    "Transcriber",
    "TranscriptionEngine",
    "TranscriptionService",
    "WhisperEngine",
    "JsonlFormatter",
    "TextFormatter",
    "available_formats",
    "create_formatter",
    "register_formatter",
    "SpeechEndpointer",
    "TranscriptLine",
    "Utterance",
    "TranscriptionPipeline",
    "TranscriptWriter",
    "TranslationWriter",
    "CompositeWriter",
    "Settings",
    "platform_for",
    "ArgosTranslator",
    "CachingTranslator",
    "ClaudeTranslator",
    "IdentityTranslator",
    "TranslationError",
    "Translator",
    "available_translators",
    "create_translator",
    "normalise_language",
    "register_translator",
    "FRAME_MS",
    "FRAME_SAMPLES",
    "SAMPLE_RATE",
    "SOURCE_MIC",
    "SOURCE_MICROPHONE",
    "SOURCE_SYS",
    "SOURCE_SYSTEM",
    "build_settings",
    "main",
    "parse_args",
]
