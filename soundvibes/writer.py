"""Writing transcript lines to disk, flushed so a kill never loses speech."""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Protocol, Sequence, Union

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
    """Renders each line once and fans it out to the main and per-language files."""

    def __init__(
        self,
        path: Path,
        formatter: Union[LineFormatter, str] = CONFIG.output.format,
        split_by_language: bool = False,
        languages: Sequence[str] = (),
        sink_factory=FileSink,
    ) -> None:
        self._formatter = create_formatter(formatter) if isinstance(formatter, str) else formatter
        self._path = Path(path)
        self._main = sink_factory(self._path)
        self._per_language: dict[str, TranscriptSink] = {}
        if split_by_language:
            for code in languages:
                language_path = self._path.with_name(
                    f"{self._path.stem}.{code}{self._path.suffix}"
                )
                self._per_language[code] = sink_factory(language_path)
        self._write_header()

    def write(self, line: TranscriptLine) -> str:
        rendered = self._formatter.format(line)
        for sink in self._sinks_for(line.language):
            sink.write(rendered)
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
        formatter: Union[LineFormatter, str],
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

    # ── internals ────────────────────────────────────────────────────────

    def _text_for(self, line: TranscriptLine, source_language: str,
                  target_language: str) -> Optional[str]:
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
            print(f"[translate] {error}\n"
                  f"Translation is switched off for the rest of this run.",
                  file=sys.stderr)
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
