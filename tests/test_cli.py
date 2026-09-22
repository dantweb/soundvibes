"""Argument parsing produces settings objects; no side effects at parse time."""

from pathlib import Path

import pytest

from soundvibes.cli import build_settings, parse_args
from soundvibes.config import CONFIG


class TestDefaults:
    """Defaults come from config.yaml, so these assert the wiring rather than
    the values — editing config.yaml must never turn the suite red."""

    def test_defaults_are_taken_from_the_config_file(self):
        settings = build_settings(parse_args([]))

        assert settings.output.path == Path(CONFIG.output.path)
        assert settings.output.format_name == CONFIG.output.format
        assert settings.transcription.languages == tuple(CONFIG.transcription.languages)
        assert settings.transcription.model_size == CONFIG.transcription.model_size

    def test_both_sources_are_captured_unless_told_otherwise(self):
        settings = build_settings(parse_args([]))
        assert settings.capture.capture_microphone is True
        assert settings.capture.capture_system is True

    def test_endpointer_defaults_are_taken_from_the_config_file(self):
        endpointer = build_settings(parse_args([])).endpointer
        assert endpointer.silence_seconds == CONFIG.endpointer.silence_seconds
        assert endpointer.min_speech_seconds == CONFIG.endpointer.min_speech_seconds
        assert endpointer.max_speech_seconds == CONFIG.endpointer.max_speech_seconds
        assert endpointer.eager_after_seconds == CONFIG.endpointer.eager_after_seconds
        assert endpointer.eager_silence_seconds == CONFIG.endpointer.eager_silence_seconds
        assert endpointer.sensitivity == CONFIG.endpointer.sensitivity


class TestOverrides:
    def test_languages_are_split_and_trimmed(self):
        settings = build_settings(parse_args(["--languages", " en , de "]))
        assert settings.transcription.languages == ("en", "de")

    def test_empty_language_list_is_rejected(self):
        with pytest.raises(SystemExit, match="at least one language"):
            build_settings(parse_args(["--languages", " , "]))

    def test_output_and_format(self):
        settings = build_settings(parse_args(["-o", "/tmp/x.jsonl", "--format", "jsonl"]))
        assert settings.output.path == Path("/tmp/x.jsonl")
        assert settings.output.format_name == "jsonl"

    def test_capture_can_be_limited_to_one_source(self):
        assert build_settings(parse_args(["--no-system"])).capture.capture_system is False
        assert build_settings(parse_args(["--no-mic"])).capture.capture_microphone is False

    def test_disabling_both_sources_is_rejected(self):
        with pytest.raises(SystemExit, match="Nothing to capture"):
            build_settings(parse_args(["--no-mic", "--no-system"]))

    def test_tuning_knobs_are_carried_through(self):
        settings = build_settings(
            parse_args(
                [
                    "--silence",
                    "1.2",
                    "--sensitivity",
                    "2.0",
                    "--model",
                    "medium",
                    "--beam-size",
                    "3",
                    "--split-by-language",
                    "--quiet",
                ]
            )
        )

        assert settings.endpointer.silence_seconds == 1.2
        assert settings.endpointer.sensitivity == 2.0
        assert settings.transcription.model_size == "medium"
        assert settings.transcription.beam_size == 3
        assert settings.output.split_by_language is True
        assert settings.output.quiet is True

    def test_device_selectors_are_preserved_verbatim(self):
        settings = build_settings(
            parse_args(["--input-device", "2", "--system-device", "BlackHole"])
        )
        assert settings.capture.input_device == "2"
        assert settings.capture.system_device == "BlackHole"

    def test_unknown_format_is_rejected_at_parse_time(self):
        with pytest.raises(SystemExit):
            parse_args(["--format", "yaml"])


class TestSettingsAreImmutable:
    def test_settings_cannot_be_mutated_after_construction(self):
        settings = build_settings(parse_args([]))
        with pytest.raises(Exception):
            settings.transcription.model_size = "large-v3"


class TestTranslation:
    def test_translation_defaults_come_from_the_config_file(self):
        translation = build_settings(parse_args([])).translation
        assert translation.targets == tuple(CONFIG.translation.targets)
        assert translation.enabled is bool(CONFIG.translation.targets)

    def test_translation_is_off_when_no_targets_are_configured(self):
        from soundvibes.settings import TranslationSettings

        assert TranslationSettings(targets=()).enabled is False

    def test_targets_are_normalised(self):
        translation = build_settings(parse_args(["--translate", "RU, en-US ,FR"])).translation
        assert translation.targets == ("ru", "en", "fr")
        assert translation.enabled is True

    def test_backend_default_comes_from_the_config_file(self):
        settings = build_settings(parse_args(["--translate", "ru"]))
        assert settings.translation.backend == CONFIG.translation.backend

    def test_backend_can_be_chosen(self):
        settings = build_settings(parse_args(["--translate", "ru", "--translator", "claude"]))
        assert settings.translation.backend == "claude"

    def test_unknown_backend_is_rejected_at_parse_time(self):
        with pytest.raises(SystemExit):
            parse_args(["--translator", "babelfish"])


class TestEagerFlags:
    def test_eager_split_can_be_tuned_from_the_command_line(self):
        endpointer = build_settings(
            parse_args(["--eager-after", "6", "--eager-silence", "0.4"])
        ).endpointer
        assert endpointer.eager_after_seconds == 6.0
        assert endpointer.eager_silence_seconds == 0.4
