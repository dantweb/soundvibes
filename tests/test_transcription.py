"""Transcription policy: language constraining, hallucination filtering, assembly.

The engine is faked at the transport seam — the boundary the real WhisperEngine
adapts — so these assert our logic, not faster-whisper's.
"""

import pytest
from conftest import FakeEngine, make_result

from soundvibes.config import CONFIG
from soundvibes.transcription import (
    EngineResult,
    HallucinationFilter,
    Segment,
    TextAssembler,
    TranscriptionService,
)


class TestHallucinationFilter:
    # The list itself lives in config.yaml and is the user's to edit, so assert
    # that whatever is configured is honoured — not a copy of today's contents.
    @pytest.mark.parametrize("text", list(CONFIG.transcription.hallucinations))
    def test_every_configured_phrase_is_rejected(self, text):
        assert HallucinationFilter().is_hallucination(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Thank you for sending the contract over.",
            "I'll take a look tonight.",
            "Guten Tag, dies ist ein deutscher Testsatz.",
        ],
    )
    def test_real_speech_survives(self, text):
        assert not HallucinationFilter().is_hallucination(text)

    def test_matching_ignores_case_and_trailing_punctuation(self):
        noise = HallucinationFilter(extra_phrases={"mumble mumble"})
        punctuation = CONFIG.transcription.trailing_punctuation.strip()[:1]
        assert noise.is_hallucination(f"  MUMBLE MUMBLE{punctuation}  ")

    def test_extra_phrases_can_be_added_without_editing_the_class(self):
        custom = HallucinationFilter(extra_phrases={"copyright wdr"})
        assert custom.is_hallucination("Copyright WDR")
        configured = next(iter(CONFIG.transcription.hallucinations))
        assert custom.is_hallucination(configured)  # configured ones still apply


NOISE = "supercalifragilistic filler"


#: Thresholds these tests own, so config.yaml can be tuned without breaking them.
MAX_NO_SPEECH = 0.6
MIN_AVERAGE_LOGPROB = -1.0


def assembler():
    """An assembler whose blocklist and thresholds this test owns."""
    return TextAssembler(
        HallucinationFilter(extra_phrases={NOISE}),
        max_no_speech_probability=MAX_NO_SPEECH,
        min_average_logprob=MIN_AVERAGE_LOGPROB,
    )


class TestTextAssembler:
    def test_segments_are_joined(self):
        segments = [Segment("Hello there.", 0.01, -0.2), Segment("How are you?", 0.01, -0.3)]
        assert assembler().assemble(segments) == "Hello there. How are you?"

    def test_low_confidence_segments_are_dropped(self):
        segments = [Segment("real speech", 0.01, -0.2), Segment("garbage", 0.01, -2.0)]
        assert assembler().assemble(segments) == "real speech"

    def test_probable_silence_is_dropped(self):
        segments = [Segment("real speech", 0.01, -0.2), Segment("ghost", 0.9, -0.2)]
        assert assembler().assemble(segments) == "real speech"

    def test_hallucinated_segments_are_dropped(self):
        segments = [Segment(NOISE, 0.01, -0.2), Segment("actual words", 0.01, -0.2)]
        assert assembler().assemble(segments) == "actual words"

    def test_output_that_is_entirely_a_hallucination_becomes_empty(self):
        assert assembler().assemble([Segment(NOISE, 0.01, -0.2)]) == ""

    def test_no_segments_yields_empty_text(self):
        assert assembler().assemble([]) == ""


class TestAssemblerDefaults:
    """The defaults themselves come from config.yaml — that wiring is the test."""

    def test_thresholds_are_taken_from_the_config_file(self):
        default = TextAssembler()
        assert default._max_no_speech_probability == CONFIG.transcription.max_no_speech_probability
        assert default._min_average_logprob == CONFIG.transcription.min_average_logprob


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
        engine = FakeEngine(
            [
                make_result(
                    "bonjour",
                    "fr",
                    0.55,
                    all_probabilities=[("fr", 0.55), ("de", 0.31), ("en", 0.10)],
                ),
                make_result("guten tag", "de", 0.31),
            ]
        )

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
        engine = FakeEngine(
            [
                make_result("bonjour", "fr", 0.9, all_probabilities=[("fr", 0.9), ("it", 0.1)]),
            ]
        )

        line = self.service(engine).transcribe(utterance)

        assert len(engine.calls) == 1
        assert line.language == "fr"

    def test_empty_transcription_yields_no_line(self, utterance):
        engine = FakeEngine([EngineResult([], "en", 0.9, [])])
        assert self.service(engine).transcribe(utterance) is None

    def test_pure_hallucination_yields_no_line(self, utterance):
        configured = next(iter(CONFIG.transcription.hallucinations))
        engine = FakeEngine([make_result(configured, "en", 0.9)])
        assert self.service(engine).transcribe(utterance) is None

    def test_duration_is_carried_from_the_utterance(self, utterance):
        engine = FakeEngine([make_result()])
        line = self.service(engine).transcribe(utterance)
        assert line.duration_seconds == pytest.approx(1.0, abs=0.01)
