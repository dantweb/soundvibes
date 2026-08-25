"""Argument parsing produces settings objects; no side effects at parse time."""
from pathlib import Path

import pytest

from soundvibes.cli import build_settings, parse_args


class TestDefaults:
    def test_sensible_defaults(self):
        settings = build_settings(parse_args([]))

        assert settings.output.path == Path("transcripts/transcript.txt")
        assert settings.output.format_name == "text"
        assert settings.transcription.languages == ("en", "de", "ru")
        assert settings.transcription.model_size == "small"
        assert settings.capture.capture_microphone is True
        assert settings.capture.capture_system is True

    def test_endpointer_defaults_match_the_documented_values(self):
        endpointer = build_settings(parse_args([])).endpointer
        assert endpointer.silence_seconds == 0.7
        assert endpointer.min_speech_seconds == 0.4
        assert endpointer.max_speech_seconds == 20.0
        assert endpointer.sensitivity == 3.0


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
        settings = build_settings(parse_args([
            "--silence", "1.2", "--sensitivity", "2.0", "--model", "medium",
            "--beam-size", "3", "--split-by-language", "--quiet",
        ]))

        assert settings.endpointer.silence_seconds == 1.2
        assert settings.endpointer.sensitivity == 2.0
        assert settings.transcription.model_size == "medium"
        assert settings.transcription.beam_size == 3
        assert settings.output.split_by_language is True
        assert settings.output.quiet is True

    def test_device_selectors_are_preserved_verbatim(self):
        settings = build_settings(parse_args(["--input-device", "2",
                                              "--system-device", "BlackHole"]))
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
