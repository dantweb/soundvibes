"""translate.<LANG>.txt files: one per target language, alongside the transcript."""
import datetime as dt

import pytest

from soundvibes.formatters import TextFormatter
from soundvibes.models import TranscriptLine
from soundvibes.translation import FILE_PREFIX, TranslatorUnavailable
from soundvibes.writer import CompositeWriter, TranscriptWriter, TranslationWriter


class StubTranslator:
    def __init__(self, failing_targets=(), unavailable=False):
        self.calls = []
        self._failing_targets = set(failing_targets)
        self._unavailable = unavailable

    def translate(self, text, source_language, target_language):
        self.calls.append((text, source_language, target_language))
        if self._unavailable:
            raise TranslatorUnavailable("backend is not installed")
        if target_language in self._failing_targets:
            raise RuntimeError("backend exploded")
        return f"<{target_language}>{text}"


def line(text="Guten Tag.", language="de", source="MIC"):
    return TranscriptLine(source=source, language=language, text=text,
                          started_at=dt.datetime(2026, 8, 25, 13, 41, 39),
                          duration_seconds=1.0, language_probability=0.9)


class TestFileNaming:
    def test_one_uppercase_file_per_target_language(self, tmp_path):
        writer = TranslationWriter(tmp_path / "transcript.txt", TextFormatter(),
                                   StubTranslator(), ["ru", "en"])
        writer.write(line())
        writer.close()

        assert (tmp_path / f"{FILE_PREFIX}.RU.txt").exists()
        assert (tmp_path / f"{FILE_PREFIX}.EN.txt").exists()

    def test_files_sit_beside_the_transcript(self, tmp_path):
        nested = tmp_path / "recordings"
        writer = TranslationWriter(nested / "transcript.txt", TextFormatter(),
                                   StubTranslator(), ["fr"])
        writer.close()

        assert (nested / f"{FILE_PREFIX}.FR.txt").exists()

    def test_the_transcript_suffix_is_reused(self, tmp_path):
        writer = TranslationWriter(tmp_path / "transcript.jsonl", TextFormatter(),
                                   StubTranslator(), ["ru"])
        writer.close()
        assert (tmp_path / f"{FILE_PREFIX}.RU.jsonl").exists()


class TestTranslationContent:
    def test_every_line_is_translated_into_every_target(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(), ["ru", "fr"])
        writer.write(line("Guten Tag.", "de"))
        writer.close()

        assert "<ru>Guten Tag." in (tmp_path / f"{FILE_PREFIX}.RU.txt").read_text()
        assert "<fr>Guten Tag." in (tmp_path / f"{FILE_PREFIX}.FR.txt").read_text()

    def test_lines_already_in_the_target_language_are_copied_not_translated(self, tmp_path):
        """A German line needs no translating for translate.DE.txt."""
        translator = StubTranslator()
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(), translator,
                                   ["de", "ru"])

        writer.write(line("Guten Tag.", "de"))
        writer.close()

        assert translator.calls == [("Guten Tag.", "de", "ru")]
        assert "Guten Tag." in (tmp_path / f"{FILE_PREFIX}.DE.txt").read_text()

    def test_the_target_language_is_shown_on_the_line(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(), ["ru"])
        writer.write(line("Guten Tag.", "de"))
        writer.close()

        assert "[ru]" in (tmp_path / f"{FILE_PREFIX}.RU.txt").read_text()

    def test_the_source_marker_is_preserved(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(), ["ru"])
        writer.write(line("Guten Tag.", "de", source="SYS"))
        writer.close()

        assert "[SYS]" in (tmp_path / f"{FILE_PREFIX}.RU.txt").read_text()

    def test_all_languages_land_in_the_same_target_file(self, tmp_path):
        """The point of the feature: one readable file per language you speak."""
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(), ["ru"])
        writer.write(line("Guten Tag.", "de"))
        writer.write(line("Hello there.", "en"))
        writer.close()

        translated = (tmp_path / f"{FILE_PREFIX}.RU.txt").read_text()
        assert "<ru>Guten Tag." in translated
        assert "<ru>Hello there." in translated


class TestFailureHandling:
    def test_a_failing_backend_does_not_lose_the_other_languages(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(failing_targets={"ru"}), ["ru", "fr"])

        writer.write(line("Guten Tag.", "de"))
        writer.close()

        assert "<fr>Guten Tag." in (tmp_path / f"{FILE_PREFIX}.FR.txt").read_text()
        assert writer.failures == 1

    def test_a_failing_backend_never_raises_into_the_pipeline(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(failing_targets={"ru"}), ["ru"])
        writer.write(line())  # must not raise
        writer.close()

    def test_a_missing_backend_is_reported_once_then_translation_stops(self, tmp_path, capsys):
        """Six targets times every utterance is the same install hint over and over.
        Say it once and stop asking."""
        translator = StubTranslator(unavailable=True)
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(), translator,
                                   ["ru", "pl", "hu"])

        writer.write(line("Guten Tag.", "de"))
        writer.write(line("Hello there.", "en"))
        writer.close()

        assert writer.disabled
        assert translator.calls == [("Guten Tag.", "de", "ru")]
        errors = capsys.readouterr().err
        assert errors.count("not installed") == 1
        assert "switched off for the rest of this run" in errors

    def test_a_missing_backend_still_returns_the_line_to_the_pipeline(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(unavailable=True), ["ru"])
        assert writer.write(line("Guten Tag.")) == "Guten Tag."
        assert writer.write(line("Noch einmal.")) == "Noch einmal."
        writer.close()


class TestCompositeWriter:
    def test_the_primary_rendering_is_returned(self, tmp_path):
        transcript = TranscriptWriter(tmp_path / "t.txt", TextFormatter())  # explicit
        translation = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                        StubTranslator(), ["ru"])
        writer = CompositeWriter(transcript, translation)

        rendered = writer.write(line())
        writer.close()

        assert rendered == "[13:41:39] [MIC] [de] Guten Tag."
        assert "<ru>Guten Tag." in (tmp_path / f"{FILE_PREFIX}.RU.txt").read_text()

    def test_closing_closes_every_member(self, tmp_path):
        class Spy:
            closed = False

            def write(self, line):
                return "x"

            def close(self):
                self.closed = True

        first, second = Spy(), Spy()
        CompositeWriter(first, second).close()

        assert first.closed and second.closed


class TestEcho:
    """`make start fr` should show the translation, not just write it to a file."""

    def test_translated_lines_are_echoed_when_a_callback_is_given(self, tmp_path):
        echoed = []
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(), StubTranslator(),
                                   ["ru"], on_line=echoed.append)

        writer.write(line("Guten Tag.", "de"))
        writer.close()

        assert echoed == ["[13:41:39] [MIC] [ru] <ru>Guten Tag."]

    def test_nothing_is_echoed_without_a_callback(self, tmp_path):
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(), ["ru"])
        writer.write(line())  # must not raise
        writer.close()

    def test_a_failed_target_is_not_echoed(self, tmp_path):
        echoed = []
        writer = TranslationWriter(tmp_path / "t.txt", TextFormatter(),
                                   StubTranslator(failing_targets={"ru"}), ["ru", "fr"],
                                   on_line=echoed.append)

        writer.write(line("Guten Tag.", "de"))
        writer.close()

        assert len(echoed) == 1
        assert "[fr]" in echoed[0]
