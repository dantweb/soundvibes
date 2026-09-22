"""Transcript writing: fan-out to per-language files, flushed after every line."""

import datetime as dt

from soundvibes.formatters import JsonlFormatter, TextFormatter
from soundvibes.models import TranscriptLine
from soundvibes.writer import TranscriptWriter


def line(text="Guten Tag.", language="de", source="MIC"):
    return TranscriptLine(
        source=source,
        language=language,
        text=text,
        started_at=dt.datetime(2026, 8, 25, 13, 41, 39),
        duration_seconds=1.0,
        language_probability=0.9,
    )


class TestTranscriptWriter:
    def test_writes_a_rendered_line_and_returns_it(self, tmp_path):
        path = tmp_path / "transcript.txt"
        writer = TranscriptWriter(path, TextFormatter())

        rendered = writer.write(line())
        writer.close()

        assert rendered == "[13:41:39] [MIC] [de] Guten Tag."
        assert rendered in path.read_text()

    def test_appends_rather_than_truncating(self, tmp_path):
        path = tmp_path / "transcript.txt"
        path.write_text("earlier session\n")

        writer = TranscriptWriter(path, TextFormatter())
        writer.write(line())
        writer.close()

        assert "earlier session" in path.read_text()

    def test_missing_parent_directory_is_created(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "transcript.txt"
        TranscriptWriter(path, TextFormatter()).close()
        assert path.exists()

    def test_content_survives_without_close(self, tmp_path):
        """Killing the process must not lose transcribed speech."""
        path = tmp_path / "transcript.txt"
        writer = TranscriptWriter(path, TextFormatter())

        writer.write(line())

        assert "Guten Tag." in path.read_text()  # flushed, not buffered

    def test_text_format_writes_a_session_header(self, tmp_path):
        path = tmp_path / "transcript.txt"
        TranscriptWriter(path, TextFormatter()).close()
        assert "soundvibes session started" in path.read_text()

    def test_jsonl_format_writes_no_header(self, tmp_path):
        path = tmp_path / "transcript.jsonl"
        writer = TranscriptWriter(path, JsonlFormatter())
        writer.write(line())
        writer.close()

        assert path.read_text().lstrip().startswith("{")

    def test_format_may_be_named_instead_of_constructed(self, tmp_path):
        writer = TranscriptWriter(tmp_path / "t.txt", "text")
        rendered = writer.write(line())
        writer.close()
        assert rendered.startswith("[13:41:39]")


class TestPerLanguageSplitting:
    def test_each_language_gets_its_own_file(self, tmp_path):
        path = tmp_path / "transcript.txt"
        writer = TranscriptWriter(
            path, TextFormatter(), split_by_language=True, languages=["en", "de", "ru"]
        )

        writer.write(line("Guten Tag.", "de"))
        writer.write(line("Hello there.", "en"))
        writer.close()

        assert "Guten Tag." in (tmp_path / "transcript.de.txt").read_text()
        assert "Hello there." in (tmp_path / "transcript.en.txt").read_text()
        assert "Guten Tag." not in (tmp_path / "transcript.en.txt").read_text()

    def test_every_line_still_reaches_the_main_file(self, tmp_path):
        path = tmp_path / "transcript.txt"
        writer = TranscriptWriter(
            path, TextFormatter(), split_by_language=True, languages=["en", "de"]
        )

        writer.write(line("Guten Tag.", "de"))
        writer.write(line("Hello there.", "en"))
        writer.close()

        combined = path.read_text()
        assert "Guten Tag." in combined and "Hello there." in combined

    def test_unexpected_language_does_not_crash(self, tmp_path):
        writer = TranscriptWriter(
            tmp_path / "t.txt", TextFormatter(), split_by_language=True, languages=["en"]
        )

        rendered = writer.write(line("Bonjour.", "fr"))
        writer.close()

        assert "Bonjour." in rendered
        assert not (tmp_path / "t.fr.txt").exists()

    def test_splitting_off_creates_no_extra_files(self, tmp_path):
        writer = TranscriptWriter(tmp_path / "t.txt", TextFormatter(), languages=["en", "de"])
        writer.write(line())
        writer.close()

        assert sorted(p.name for p in tmp_path.iterdir()) == ["t.txt"]
