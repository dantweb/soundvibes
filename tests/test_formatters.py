"""Output formats are strategies, so a new one adds a class instead of a branch."""

import datetime as dt
import json

import pytest

from soundvibes.formatters import (
    JsonlFormatter,
    TextFormatter,
    available_formats,
    create_formatter,
    register_formatter,
)
from soundvibes.models import TranscriptLine

LINE = TranscriptLine(
    source="MIC",
    language="de",
    text="Guten Tag.",
    started_at=dt.datetime(2026, 8, 25, 13, 41, 39),
    duration_seconds=1.234,
    language_probability=0.876,
)


class TestTextFormatter:
    def test_renders_clock_source_language_and_text(self):
        assert TextFormatter().format(LINE) == "[13:41:39] [MIC] [de] Guten Tag."

    def test_header_marks_the_session(self):
        header = TextFormatter().header(dt.datetime(2026, 8, 25, 13, 41, 38))
        assert "soundvibes session started 2026-08-25 13:41:38" in header


class TestJsonlFormatter:
    def test_emits_one_json_object(self):
        payload = json.loads(JsonlFormatter().format(LINE))

        assert payload["source"] == "MIC"
        assert payload["language"] == "de"
        assert payload["text"] == "Guten Tag."
        assert payload["timestamp"] == "2026-08-25T13:41:39"
        assert payload["duration_seconds"] == 1.23
        assert payload["language_probability"] == 0.876

    def test_non_ascii_is_kept_readable(self):
        line = TranscriptLine("MIC", "ru", "Добрый день.", LINE.started_at, 1.0, 0.9)
        assert "Добрый день." in JsonlFormatter().format(line)

    def test_has_no_header(self):
        assert JsonlFormatter().header(dt.datetime.now()) is None


class TestRegistry:
    def test_builtin_formats_are_available(self):
        assert set(available_formats()) >= {"text", "jsonl"}

    def test_create_by_name(self):
        assert isinstance(create_formatter("text"), TextFormatter)
        assert isinstance(create_formatter("jsonl"), JsonlFormatter)

    def test_unknown_format_names_the_alternatives(self):
        with pytest.raises(ValueError, match="text"):
            create_formatter("yaml")

    def test_a_new_format_needs_no_change_to_existing_code(self):
        """Open/closed: registration is the extension point."""

        class SubtitleFormatter:
            def format(self, line):
                return f"{line.started_at:%H:%M:%S} --> {line.text}"

            def header(self, moment):
                return None

        register_formatter("srt", SubtitleFormatter)
        try:
            assert "srt" in available_formats()
            assert create_formatter("srt").format(LINE).endswith("Guten Tag.")
        finally:
            register_formatter("srt", None)
