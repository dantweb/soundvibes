"""Transcription: an engine seam, plus the policy we apply on top of it.

The engine boundary is deliberately narrow — audio in, segments and language
out — so faster-whisper can be swapped for anything else, and so the policy
below (language constraining, hallucination filtering) is testable without a
model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, Sequence

import numpy as np

from .models import TranscriptLine, Utterance

# Whisper happily invents these when handed near-silence or music.
DEFAULT_HALLUCINATIONS = frozenset({
    "thank you.", "thanks for watching!", "you", "bye.",
    "untertitel von stephanie geiges", "untertitelung des zdf, 2020",
    "продолжение следует...", "субтитры сделал dimatorzok",
    "редактор субтитров а.синецкая корректор а.егорова", "amara.org",
})

TRAILING_PUNCTUATION = " .!?…"


@dataclass
class Segment:
    """One piece of transcribed audio, with the engine's own quality signals."""

    text: str
    no_speech_probability: float
    average_logprob: float


@dataclass
class EngineResult:
    segments: Sequence[Segment]
    language: str
    language_probability: float
    all_language_probabilities: Sequence[tuple[str, float]] = field(default_factory=list)


class TranscriptionEngine(Protocol):
    """Everything soundvibes needs from a speech-to-text model."""

    def transcribe(self, audio: np.ndarray, language: Optional[str],
                   beam_size: int) -> EngineResult: ...


class WhisperEngine:
    """Adapter for faster-whisper."""

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8", announce=print) -> None:
        from faster_whisper import WhisperModel  # noqa: PLC0415 - slow import

        announce(f"Loading whisper model {model_size!r} ({device}/{compute_type})...")
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        announce("Model ready.")

    def transcribe(self, audio: np.ndarray, language: Optional[str],
                   beam_size: int) -> EngineResult:
        segments, info = self._model.transcribe(
            audio,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return EngineResult(
            segments=[Segment(segment.text, segment.no_speech_prob, segment.avg_logprob)
                      for segment in segments],
            language=info.language,
            language_probability=info.language_probability,
            all_language_probabilities=info.all_language_probs or [],
        )


class HallucinationFilter:
    """Recognises the stock phrases whisper produces from silence and music."""

    def __init__(self, extra_phrases: Optional[Iterable[str]] = None) -> None:
        # Both the blocklist and the candidate are normalised the same way.
        # They were not before, so "Thank you." only ever matched as a whole
        # line and slipped through when whisper mixed it into real speech.
        phrases = set(DEFAULT_HALLUCINATIONS) | {p for p in (extra_phrases or ())}
        self._phrases = {self._normalise(phrase) for phrase in phrases}

    def is_hallucination(self, text: str) -> bool:
        return self._normalise(text) in self._phrases

    @staticmethod
    def _normalise(text: str) -> str:
        return text.strip().lower().strip(TRAILING_PUNCTUATION)


class TextAssembler:
    """Joins segments into a line, dropping the ones that are not real speech."""

    def __init__(self, hallucinations: Optional[HallucinationFilter] = None,
                 max_no_speech_probability: float = 0.6,
                 min_average_logprob: float = -1.0) -> None:
        self._hallucinations = hallucinations or HallucinationFilter()
        self._max_no_speech_probability = max_no_speech_probability
        self._min_average_logprob = min_average_logprob

    def assemble(self, segments: Iterable[Segment]) -> str:
        kept = []
        for segment in segments:
            if not self._is_plausible(segment):
                continue
            piece = segment.text.strip()
            if piece and not self._hallucinations.is_hallucination(piece):
                kept.append(piece)
        text = " ".join(kept).strip()
        return "" if self._hallucinations.is_hallucination(text) else text

    def _is_plausible(self, segment: Segment) -> bool:
        return (segment.no_speech_probability <= self._max_no_speech_probability
                and segment.average_logprob >= self._min_average_logprob)


class TranscriptionService:
    """Applies our language policy to whatever the engine returns."""

    def __init__(self, engine: TranscriptionEngine, languages: Sequence[str],
                 beam_size: int = 5, assembler: Optional[TextAssembler] = None) -> None:
        self._engine = engine
        self._languages = list(languages)
        self._beam_size = beam_size
        self._assembler = assembler or TextAssembler()

    def transcribe(self, utterance: Utterance) -> Optional[TranscriptLine]:
        result = self._engine.transcribe(
            utterance.audio, language=self._pinned_language(), beam_size=self._beam_size
        )
        result = self._constrain_language(utterance, result)

        text = self._assembler.assemble(result.segments)
        if not text:
            return None
        return TranscriptLine(
            source=utterance.source,
            language=result.language,
            text=text,
            started_at=utterance.started_at,
            duration_seconds=utterance.duration_seconds,
            language_probability=result.language_probability,
        )

    def _pinned_language(self) -> Optional[str]:
        """With one allowed language there is nothing to detect."""
        return self._languages[0] if len(self._languages) == 1 else None

    def _constrain_language(self, utterance: Utterance,
                            result: EngineResult) -> EngineResult:
        """Whisper knows ~100 languages; force the answer into the allowed set."""
        if len(self._languages) <= 1 or result.language in self._languages:
            return result

        best = self._best_allowed(result.all_language_probabilities)
        if best is None:
            return result

        language, probability = best
        retried = self._engine.transcribe(utterance.audio, language=language,
                                          beam_size=self._beam_size)
        return EngineResult(
            segments=retried.segments,
            language=language,
            language_probability=probability,
            all_language_probabilities=retried.all_language_probabilities,
        )

    def _best_allowed(self, probabilities) -> Optional[tuple[str, float]]:
        allowed = [(code, probability) for code, probability in (probabilities or [])
                   if code in self._languages]
        return max(allowed, key=lambda item: item[1]) if allowed else None


class Transcriber:
    """Convenience facade: build the engine and the service in one step."""

    def __init__(self, model_size: str, languages: Sequence[str], device: str,
                 compute_type: str, beam_size: int) -> None:
        engine = WhisperEngine(model_size=model_size, device=device,
                               compute_type=compute_type)
        self._service = TranscriptionService(engine, languages, beam_size)

    def transcribe(self, utterance: Utterance) -> Optional[TranscriptLine]:
        return self._service.transcribe(utterance)
