"""Composition root: builds the object graph and runs it.

Every collaborator is injectable, which is what lets the whole program be
exercised in tests without a microphone or a model.
"""

from __future__ import annotations

import queue
import signal
import sys
import threading
from collections.abc import Sequence

from .capture import AudioSource
from .constants import SOURCE_MICROPHONE, SOURCE_SYSTEM
from .devices import AudioBackend, DeviceRegistry, SoundDeviceBackend
from .endpointing import SpeechEndpointer
from .models import Utterance
from .pipeline import TranscriptionPipeline
from .platforms import Platform, platform_for
from .settings import Settings
from .transcription import TranscriptionService, WhisperEngine
from .translation import CachingTranslator, create_translator
from .writer import BackgroundWriter, CompositeWriter, TranscriptWriter, TranslationWriter


class Application:
    def __init__(
        self,
        settings: Settings,
        backend: AudioBackend | None = None,
        platform: Platform | None = None,
        engine=None,
        announce=print,
    ) -> None:
        self._settings = settings
        self._backend = backend or SoundDeviceBackend()
        self._platform = platform or platform_for()
        self._engine = engine
        self._announce = announce
        self._registry = DeviceRegistry(self._backend)
        self._stop_event = threading.Event()

    def run(self) -> int:
        settings = self._settings
        utterances: queue.Queue[Utterance] = queue.Queue()
        sources = self.build_sources(utterances)

        service = TranscriptionService(
            engine=self._engine
            or WhisperEngine(
                model_size=settings.transcription.model_size,
                device=settings.transcription.device,
                compute_type=settings.transcription.compute_type,
                announce=self._announce,
            ),
            languages=settings.transcription.languages,
            beam_size=settings.transcription.beam_size,
        )
        # Echoing is the writers' job (see _build_writer), so the original line
        # reaches the console before its translations are even queued.
        writer = self._build_writer()
        pipeline = TranscriptionPipeline(service, writer)

        self._install_signal_handlers()
        for source in sources:
            source.start()
        self._announce_ready(sources)

        try:
            pipeline.run(utterances, sources, self._stop_event)
        finally:
            self._stop_event.set()
            for source in sources:
                source.join(timeout=2.0)
            # Anything endpointed during shutdown still deserves a transcript line.
            pipeline.drain(utterances)
            writer.close()

        self._announce(
            f"\nWrote {pipeline.lines_written} transcript line(s) to "
            f"{settings.output.path.resolve()}"
        )
        return 0

    def _build_writer(self):
        settings = self._settings
        echo = None if settings.output.quiet else self._echo
        transcript = TranscriptWriter(
            path=settings.output.path,
            formatter=settings.output.format_name,
            split_by_language=settings.output.split_by_language,
            languages=settings.transcription.languages,
            on_line=echo,
        )
        if not settings.translation.enabled:
            return transcript

        # Cached because live speech repeats itself constantly, and every repeat
        # is otherwise a fresh model call or API round trip.
        translator = CachingTranslator(create_translator(settings.translation.backend))
        translations = TranslationWriter(
            path=settings.output.path,
            formatter=settings.output.format_name,
            translator=translator,
            target_languages=settings.translation.targets,
            # Show the translation as it happens, not just write it to a file.
            on_line=echo,
        )
        self._announce(
            f"Translating into {'/'.join(settings.translation.targets)} "
            f"via {settings.translation.backend}"
        )
        # Translation is slow and must not hold up the next utterance: it runs
        # on its own thread and trails the transcript by however long it takes.
        # The models are loaded on that thread while we start listening.
        spoken = settings.transcription.languages

        def warm_up() -> None:
            translations.warm_up(spoken[0] if spoken else "en")
            if not translations.disabled:
                self._announce("Translation ready.")

        return CompositeWriter(
            transcript,
            BackgroundWriter(
                translations, name="translation", announce=self._announce, prepare=warm_up
            ),
        )

    def build_sources(self, utterances: queue.Queue[Utterance]) -> list[AudioSource]:
        capture = self._settings.capture
        sources: list[AudioSource] = []

        if capture.capture_microphone:
            index = self._registry.resolve(capture.input_device)
            sources.append(self._source(SOURCE_MICROPHONE, index, utterances))

        if capture.capture_system:
            index = self._registry.resolve(capture.system_device)
            if index is None:
                index = self._registry.find_loopback()
            if index is None:
                print(self._platform.loopback_help(), file=sys.stderr)
            else:
                sources.append(self._source(SOURCE_SYSTEM, index, utterances))

        if not sources:
            raise SystemExit("Nothing to capture: no usable audio device was found.")
        return sources

    # ── internals ────────────────────────────────────────────────────────

    def _source(
        self, label: str, index: int | None, utterances: queue.Queue[Utterance]
    ) -> AudioSource:
        endpointer_settings = self._settings.endpointer
        return AudioSource(
            label=label,
            device=self._registry.describe(index),
            backend=self._backend,
            endpointer=SpeechEndpointer(
                silence_seconds=endpointer_settings.silence_seconds,
                min_speech_seconds=endpointer_settings.min_speech_seconds,
                max_speech_seconds=endpointer_settings.max_speech_seconds,
                eager_after_seconds=endpointer_settings.eager_after_seconds,
                eager_silence_seconds=endpointer_settings.eager_silence_seconds,
                preroll_seconds=endpointer_settings.preroll_seconds,
                sensitivity=endpointer_settings.sensitivity,
                absolute_floor=endpointer_settings.absolute_floor,
            ),
            utterances=utterances,
            stop_event=self._stop_event,
        )

    def _echo(self, rendered: str) -> None:
        print(rendered, flush=True)

    def _install_signal_handlers(self) -> None:
        def request_stop(*_arguments) -> None:
            if not self._stop_event.is_set():
                self._announce("\nStopping - draining the queue, please wait...")
                self._stop_event.set()

        for received in (signal.SIGINT, signal.SIGTERM):
            signal.signal(received, request_stop)

    def _announce_ready(self, sources: Sequence[AudioSource]) -> None:
        captured = ", ".join(f"{source.label}={source.device_name}" for source in sources)
        languages = "/".join(self._settings.transcription.languages)
        self._announce(f"Listening on {captured}")
        self._announce(
            f"Languages: {languages}   Transcript: {self._settings.output.path.resolve()}"
        )
        self._announce("Press Ctrl-C to stop.\n")
