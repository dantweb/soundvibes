"""Writing transcript lines to disk, flushed so a kill never loses speech."""

from __future__ import annotations

import datetime as dt
import queue
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .config import CONFIG
from .formatters import LineFormatter, create_formatter
from .models import TranscriptLine
from .translation import TranslatorUnavailable


class TranscriptSink(Protocol):
    def write(self, text: str) -> None: ...

    def close(self) -> None: ...


class FileSink:
    """Appends to a file, flushing after every line.

    Flushing per line is the whole point: soundvibes is normally ended with
    Ctrl-C, and buffered output would lose the tail of every session.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    def write(self, text: str) -> None:
        self._handle.write(text + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


class TranscriptWriter:
    """Renders each line once and fans it out to the main and per-language files.

    `on_line` is called with the rendered line as soon as it is written - before
    any additional writer (translation) gets to see the line - so the console
    always shows the original ahead of its translations.
    """

    def __init__(
        self,
        path: Path,
        formatter: LineFormatter | str = CONFIG.output.format,
        split_by_language: bool = False,
        languages: Sequence[str] = (),
        sink_factory=FileSink,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self._formatter = create_formatter(formatter) if isinstance(formatter, str) else formatter
        self._path = Path(path)
        self._on_line = on_line
        self._main = sink_factory(self._path)
        self._per_language: dict[str, TranscriptSink] = {}
        if split_by_language:
            for code in languages:
                language_path = self._path.with_name(f"{self._path.stem}.{code}{self._path.suffix}")
                self._per_language[code] = sink_factory(language_path)
        self._write_header()

    def write(self, line: TranscriptLine) -> str:
        rendered = self._formatter.format(line)
        for sink in self._sinks_for(line.language):
            sink.write(rendered)
        if self._on_line is not None:
            self._on_line(rendered)
        return rendered

    def close(self) -> None:
        for sink in self._all_sinks():
            sink.close()

    # ── internals ────────────────────────────────────────────────────────

    def _sinks_for(self, language: str):
        yield self._main
        specific = self._per_language.get(language)
        if specific is not None:
            yield specific

    def _all_sinks(self):
        return [self._main, *self._per_language.values()]

    def _write_header(self) -> None:
        header = self._formatter.header(dt.datetime.now())
        if header is None:
            return
        for sink in self._all_sinks():
            sink.write(header)


class TranslationWriter:
    """Writes every line into `translate.<LANG>.<ext>`, one file per target language.

    The transcript itself stays mixed-language; these files are the readable
    single-language views of the same conversation.
    """

    def __init__(
        self,
        path: Path,
        formatter: LineFormatter | str,
        translator,
        target_languages: Sequence[str],
        sink_factory=FileSink,
        on_line=None,
    ) -> None:
        from .translation import FILE_PREFIX, normalise_language  # noqa: PLC0415

        self._formatter = create_formatter(formatter) if isinstance(formatter, str) else formatter
        self._translator = translator
        self._path = Path(path)
        self._on_line = on_line
        self.failures = 0
        self.disabled = False

        self._sinks: dict[str, TranscriptSink] = {}
        for code in target_languages:
            language = normalise_language(code)
            target_path = self._path.with_name(
                f"{FILE_PREFIX}.{language.upper()}{self._path.suffix}"
            )
            self._sinks[language] = sink_factory(target_path)
        self._write_header()

    def write(self, line: TranscriptLine) -> str:
        from .translation import normalise_language  # noqa: PLC0415

        if self.disabled:
            return line.text
        source_language = normalise_language(line.language)
        for language, sink in self._sinks.items():
            if self.disabled:
                break
            text = self._text_for(line, source_language, language)
            if text is None:
                continue
            rendered = self._formatter.format(replace(line, language=language, text=text))
            sink.write(rendered)
            if self._on_line is not None:
                self._on_line(rendered)
        return line.text

    def close(self) -> None:
        for sink in self._sinks.values():
            sink.close()

    def warm_up(self, source_language: str, sample: str = "Guten Tag.") -> None:
        """Load every target's model now, so the first real line is not held up.

        Argos takes tens of seconds the first time a language pair is used
        (ctranslate2 model, stanza sentence splitter). Doing it while the
        program starts listening keeps that cost out of the conversation.
        """
        from .translation import normalise_language  # noqa: PLC0415

        probe = TranscriptLine(
            source="warm-up",
            language=source_language,
            text=sample,
            started_at=dt.datetime.now(),
            duration_seconds=0.0,
            language_probability=1.0,
        )
        source = normalise_language(source_language)
        for target in self._sinks:
            if self.disabled:
                return
            self._text_for(probe, source, target)

    # ── internals ────────────────────────────────────────────────────────

    def _text_for(
        self, line: TranscriptLine, source_language: str, target_language: str
    ) -> str | None:
        """Translated text, or None when this line could not be translated."""
        if source_language == target_language:
            return line.text  # already in the target language; nothing to do
        try:
            return self._translator.translate(line.text, source_language, target_language)
        except TranslatorUnavailable as error:
            # Nothing will change for the rest of the run, so say it once and
            # stop trying, rather than once per language per utterance.
            self.failures += 1
            self.disabled = True
            print(
                f"[translate] {error}\nTranslation is switched off for the rest of this run.",
                file=sys.stderr,
            )
            return None
        except Exception as error:  # noqa: BLE001 - one target must not sink the rest
            self.failures += 1
            print(f"[translate:{target_language}] {error}", file=sys.stderr)
            return None

    def _write_header(self) -> None:
        header = self._formatter.header(dt.datetime.now())
        if header is None:
            return
        for sink in self._sinks.values():
            sink.write(header)


_STOP = object()


class BackgroundWriter:
    """Runs another writer on its own thread, so slow work never stalls the transcript.

    Translation is the case that matters: six argos targets take around twenty
    seconds on a laptop CPU, and doing that inline held up every utterance that
    followed. `write` only queues the line and returns at once; the wrapped
    writer sees the lines in order on the worker thread. `close` finishes the
    backlog before closing the wrapped writer, so Ctrl-C loses nothing.
    """

    def __init__(
        self,
        inner,
        name: str = "background",
        announce=None,
        prepare: Callable[[], None] | None = None,
    ) -> None:
        self._inner = inner
        self._name = name
        self._announce = announce
        self._prepare = prepare
        self._queue: queue.Queue = queue.Queue()
        self.errors = 0
        self.ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"{name}-writer", daemon=True)
        self._thread.start()

    @property
    def pending(self) -> int:
        """Lines queued but not yet handled by the wrapped writer."""
        return self._queue.qsize()

    def write(self, line: TranscriptLine) -> str:
        self._queue.put(line)
        return line.text

    def close(self) -> None:
        backlog = self.pending
        if backlog and self._announce is not None:
            self._announce(f"Finishing {backlog} queued {self._name} line(s)...")
        self._queue.put(_STOP)
        self._thread.join()
        self._inner.close()

    def _run(self) -> None:
        # `prepare` (model warm-up) runs here, on the worker, so the caller's
        # thread is never blocked and lines queued meanwhile are kept in order.
        if self._prepare is not None:
            try:
                self._prepare()
            except Exception as error:  # noqa: BLE001 - a failed warm-up is not fatal
                self.errors += 1
                print(f"[{self._name}] warm-up failed: {error}", file=sys.stderr)
        self.ready.set()
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            try:
                self._inner.write(item)
            except Exception as error:  # noqa: BLE001 - the worker must outlive one bad line
                self.errors += 1
                print(f"[{self._name}] {error}", file=sys.stderr)


class CompositeWriter:
    """Fans one line out to several writers, returning the primary's rendering."""

    def __init__(self, primary, *additional) -> None:
        self._primary = primary
        self._additional = additional

    def write(self, line: TranscriptLine) -> str:
        rendered = self._primary.write(line)
        for writer in self._additional:
            writer.write(line)
        return rendered

    def close(self) -> None:
        for writer in (self._primary, *self._additional):
            writer.close()
