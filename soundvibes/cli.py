"""Command line: parse arguments, build settings, hand off to the Application."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from .app import Application
from .devices import DeviceRegistry, DeviceResolutionError, SoundDeviceBackend
from .formatters import available_formats
from .settings import (CaptureSettings, EndpointerSettings, OutputSettings, Settings,
                       TranscriptionSettings)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="soundvibes",
        description="Live speech-to-text of microphone input and system audio output.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--list-devices", action="store_true",
                        help="show audio devices and exit")
    parser.add_argument("-o", "--output", type=Path,
                        default=Path("transcripts/transcript.txt"),
                        help="transcript file (appended to, never truncated)")
    parser.add_argument("--format", choices=available_formats(), default="text",
                        help="transcript line format")
    parser.add_argument("--split-by-language", action="store_true",
                        help="also write transcript.en.txt / transcript.de.txt / ...")
    parser.add_argument("--languages", default="en,de,ru",
                        help="comma-separated whisper language codes to allow")
    parser.add_argument("--model", default="small",
                        help="whisper model: tiny/base/small/medium/large-v3")
    parser.add_argument("--device", default="cpu",
                        help="compute device for whisper: cpu or cuda")
    parser.add_argument("--compute-type", default="int8", help="ctranslate2 compute type")
    parser.add_argument("--beam-size", type=int, default=5, help="whisper beam size")
    parser.add_argument("--input-device", help="index or name of the microphone device")
    parser.add_argument("--system-device",
                        help="index or name of the loopback device for system audio")
    parser.add_argument("--no-mic", action="store_true", help="do not capture the microphone")
    parser.add_argument("--no-system", action="store_true",
                        help="do not capture system output")
    parser.add_argument("--silence", type=float, default=0.7,
                        help="seconds of silence that end an utterance")
    parser.add_argument("--min-speech", type=float, default=0.4,
                        help="shorter utterances are discarded")
    parser.add_argument("--max-speech", type=float, default=20.0,
                        help="force-split utterances longer than this")
    parser.add_argument("--sensitivity", type=float, default=3.0,
                        help="speech threshold as a multiple of the noise floor "
                             "(lower = more sensitive)")
    parser.add_argument("--quiet", action="store_true",
                        help="do not echo transcript lines to the console")
    return parser.parse_args(argv)


def build_settings(arguments: argparse.Namespace) -> Settings:
    languages = tuple(code.strip() for code in arguments.languages.split(",") if code.strip())
    if not languages:
        raise SystemExit("--languages must list at least one language code.")
    if arguments.no_mic and arguments.no_system:
        raise SystemExit("Nothing to capture: --no-mic and --no-system are both set.")

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
            sensitivity=arguments.sensitivity,
        ),
        transcription=TranscriptionSettings(
            languages=languages,
            model_size=arguments.model,
            device=arguments.device,
            compute_type=arguments.compute_type,
            beam_size=arguments.beam_size,
        ),
        output=OutputSettings(
            path=arguments.output,
            format_name=arguments.format,
            split_by_language=arguments.split_by_language,
            quiet=arguments.quiet,
        ),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_args(argv)

    if arguments.list_devices:
        print(DeviceRegistry(SoundDeviceBackend()).format_table())
        return 0

    try:
        return Application(build_settings(arguments)).run()
    except DeviceResolutionError as error:
        raise SystemExit(str(error)) from None
