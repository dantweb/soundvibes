"""Transcription policy: language constraining, hallucination filtering, assembly.

The engine is faked at the transport seam — the boundary the real WhisperEngine
adapts — so these assert our logic, not faster-whisper's.
"""
import datetime as dt

import numpy as np
import pytest

from conftest import FakeEngine, make_result
from soundvibes.models import Utterance
from soundvibes.transcription import (EngineResult, HallucinationFilter, Segment,
                                      TextAssembler, TranscriptionService)


class TestHallucinationFilter:
    @pytest.mark.parametrize("text", [
        "Thank you.", "thanks for watching!", "you", "Bye.",
        "Untertitel von Stephanie Geiges", "Продолжение следует...", "amara.org",
    ])
    def test_known_whisper_inventions_are_rejected(self, text):
        assert HallucinationFilter().is_hallucination(text)

    @pytest.mark.parametrize("text", [
        "Thank you for sending the contract over.",
        "I'll take a look tonight.",
        "Guten Tag, dies ist ein deutscher Testsatz.",
    ])
    def test_real_speech_survives(self, text):
        assert not HallucinationFilter().is_hallucination(text)

    def test_matching_ignores_case_and_trailing_punctuation(self):
        assert HallucinationFilter().is_hallucination("  THANK YOU!!  ")

    def test_extra_phrases_can_be_added_without_editing_the_class(self):
        custom = HallucinationFilter(extra_phrases={"copyright wdr"})
        assert custom.is_hallucination("Copyright WDR")
        assert custom.is_hallucination("Thank you.")  # defaults still apply


class TestTextAssembler:
    def test_segments_are_joined(self):
        segments = [Segment("Hello there.", 0.01, -0.2), Segment("How are you?", 0.01, -0.3)]
        assert TextAssembler().assemble(segments) == "Hello there. How are you?"

    def test_low_confidence_segments_are_dropped(self):
        segments = [Segment("real speech", 0.01, -0.2), Segment("garbage", 0.01, -2.0)]
        assert TextAssembler().assemble(segments) == "real speech"

    def test_probable_silence_is_dropped(self):
        segments = [Segment("real speech", 0.01, -0.2), Segment("ghost", 0.9, -0.2)]
        assert TextAssembler().assemble(segments) == "real speech"

    def test_hallucinated_segments_are_dropped(self):
        segments = [Segment("Thank you.", 0.01, -0.2), Segment("actual words", 0.01, -0.2)]
        assert TextAssembler().assemble(segments) == "actual words"

    def test_output_that_is_entirely_a_hallucination_becomes_empty(self):
        assert TextAssembler().assemble([Segment("Thank you.", 0.01, -0.2)]) == ""

    def test_no_segments_yields_empty_text(self):
        assert TextAssembler().assemble([]) == ""


class TestTranscriptionService:
    def service(self, engine, languages=("en", "de", "ru")):
        return TranscriptionService(engine=engine, languages=list(languages), beam_size=5)

    def test_produces_a_transcript_line(self, utterance):
        engine = FakeEngine([make_result("hello there", "en", 0.94)])

        line = self.service(engine).transcribe(utterance)

        assert line.text == "hello there"
        assert line.language == "en"
        assert line.source == "MIC"
        assert line.language_probability == pytest.approx(0.94)
        assert line.started_at == utterance.started_at

    def test_single_language_is_pinned_and_detection_skipped(self, utterance):
        engine = FakeEngine([make_result("hallo", "de", 0.9)])

        self.service(engine, languages=("de",)).transcribe(utterance)

        assert engine.calls[0]["language"] == "de"
        assert len(engine.calls) == 1

    def test_multiple_languages_let_whisper_detect(self, utterance):
        engine = FakeEngine([make_result("hello", "en", 0.9)])

        self.service(engine).transcribe(utterance)

        assert engine.calls[0]["language"] is None

    def test_detection_outside_the_allowed_set_is_retried_with_the_best_allowed(self, utterance):
        """Whisper knows ~100 languages; we only want ours."""
        engine = FakeEngine([
            make_result("bonjour", "fr", 0.55,
                        all_probabilities=[("fr", 0.55), ("de", 0.31), ("en", 0.10)]),
            make_result("guten tag", "de", 0.31),
        ])

        line = self.service(engine).transcribe(utterance)

        assert len(engine.calls) == 2
        assert engine.calls[1]["language"] == "de"
        assert line.language == "de"
        assert line.text == "guten tag"

    def test_allowed_detection_is_not_retried(self, utterance):
        engine = FakeEngine([make_result("hello", "en", 0.9)])
        self.service(engine).transcribe(utterance)
        assert len(engine.calls) == 1

    def test_no_allowed_language_keeps_the_original_result(self, utterance):
        engine = FakeEngine([
            make_result("bonjour", "fr", 0.9, all_probabilities=[("fr", 0.9), ("it", 0.1)]),
        ])

        line = self.service(engine).transcribe(utterance)

        assert len(engine.calls) == 1
        assert line.language == "fr"

    def test_empty_transcription_yields_no_line(self, utterance):
        engine = FakeEngine([EngineResult([], "en", 0.9, [])])
        assert self.service(engine).transcribe(utterance) is None

    def test_pure_hallucination_yields_no_line(self, utterance):
        engine = FakeEngine([make_result("Thank you.", "en", 0.9)])
        assert self.service(engine).transcribe(utterance) is None

    def test_duration_is_carried_from_the_utterance(self, utterance):
        engine = FakeEngine([make_result()])
        line = self.service(engine).transcribe(utterance)
        assert line.duration_seconds == pytest.approx(1.0, abs=0.01)
