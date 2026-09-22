"""Command line: parse arguments, build settings, hand off to the Application."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .app import Application
from .config import CONFIG
from .devices import DeviceRegistry, DeviceResolutionError, SoundDeviceBackend
from .formatters import available_formats
from .settings import (
    CaptureSettings,
    EndpointerSettings,
    OutputSettings,
    Settings,
    TranscriptionSettings,
    TranslationSettings,
)
from .translation import available_translators, normalise_language


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
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
        default=Path(CONFIG.output.path),
        help="transcript file (appended to, never truncated)",
    )
    parser.add_argument(
        "--format",
        choices=available_formats(),
        default=CONFIG.output.format,
        help="transcript line format",
    )
    parser.add_argument(
        "--split-by-language",
        action="store_true",
        help="also write transcript.en.txt / transcript.de.txt / ...",
    )
    parser.add_argument(
        "--languages",
        default=",".join(CONFIG.transcription.languages),
        help="comma-separated whisper language codes to allow",
    )
    parser.add_argument(
        "--translate",
        default=",".join(CONFIG.translation.targets),
        help="comma-separated languages to translate into; writes "
        "translate.RU.txt, translate.EN.txt, ... beside the transcript",
    )
    parser.add_argument(
        "--translator",
        choices=available_translators(),
        default=CONFIG.translation.backend,
        help="translation backend ('argos' runs offline; 'claude' sends "
        "transcript text to the Anthropic API)",
    )
    parser.add_argument(
        "--model",
        default=CONFIG.transcription.model_size,
        help="whisper model: tiny/base/small/medium/large-v3",
    )
    parser.add_argument(
        "--device",
        default=CONFIG.transcription.device,
        help="compute device for whisper: cpu or cuda",
    )
    parser.add_argument(
        "--compute-type", default=CONFIG.transcription.compute_type, help="ctranslate2 compute type"
    )
    parser.add_argument(
        "--beam-size", type=int, default=CONFIG.transcription.beam_size, help="whisper beam size"
    )
    parser.add_argument("--input-device", help="index or name of the microphone device")
    parser.add_argument(
        "--system-device", help="index or name of the loopback device for system audio"
    )
    parser.add_argument("--no-mic", action="store_true", help="do not capture the microphone")
    parser.add_argument("--no-system", action="store_true", help="do not capture system output")
    parser.add_argument(
        "--silence",
        type=float,
        default=CONFIG.endpointer.silence_seconds,
        help="seconds of silence that end an utterance",
    )
    parser.add_argument(
        "--min-speech",
        type=float,
        default=CONFIG.endpointer.min_speech_seconds,
        help="shorter utterances are discarded",
    )
    parser.add_argument(
        "--max-speech",
        type=float,
        default=CONFIG.endpointer.max_speech_seconds,
        help="force-split utterances longer than this",
    )
    parser.add_argument(
        "--eager-after",
        type=float,
        default=CONFIG.endpointer.eager_after_seconds,
        help="once an utterance is this long, a pause of --eager-silence ends it",
    )
    parser.add_argument(
        "--eager-silence",
        type=float,
        default=CONFIG.endpointer.eager_silence_seconds,
        help="the shorter pause that ends an utterance after --eager-after seconds",
    )
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=CONFIG.endpointer.sensitivity,
        help="speech threshold as a multiple of the noise floor (lower = more sensitive)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="do not echo transcript lines to the console"
    )
    return parser.parse_args(argv)


def build_settings(arguments: argparse.Namespace) -> Settings:
    languages = tuple(code.strip() for code in arguments.languages.split(",") if code.strip())
    if not languages:
        raise SystemExit("--languages must list at least one language code.")
    if arguments.no_mic and arguments.no_system:
        raise SystemExit("Nothing to capture: --no-mic and --no-system are both set.")

    translation_targets = tuple(
        normalise_language(code) for code in arguments.translate.split(",") if code.strip()
    )

    return Settings(
        capture=CaptureSettings(
            capture_microphone=not arguments.no_mic,
            capture_system=not arguments.no_system,
            input_device=arguments.input_device,
            system_device=arguments.system_device,
        ),
        endpointer=EndpointerSettings(
            silence_seconds=arguments.silence,
            min_speech_seconds=arguments.min_speech,
            max_speech_seconds=arguments.max_speech,
            eager_after_seconds=arguments.eager_after,
            eager_silence_seconds=arguments.eager_silence,
            sensitivity=arguments.sensitivity,
        ),
        transcription=TranscriptionSettings(
            languages=languages,
            model_size=arguments.model,
            device=arguments.device,
            compute_type=arguments.compute_type,
            beam_size=arguments.beam_size,
        ),
        translation=TranslationSettings(
            targets=translation_targets,
            backend=arguments.translator,
        ),
        output=OutputSettings(
            path=arguments.output,
            format_name=arguments.format,
            split_by_language=arguments.split_by_language,
            quiet=arguments.quiet,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)

    if arguments.list_devices:
        print(DeviceRegistry(SoundDeviceBackend()).format_table())
        return 0

    try:
        return Application(build_settings(arguments)).run()
    except DeviceResolutionError as error:
        raise SystemExit(str(error)) from None
