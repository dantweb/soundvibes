"""Writing transcript lines to disk, flushed so a kill never loses speech."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional, Protocol, Sequence, Union

from .formatters import LineFormatter, create_formatter
from .models import TranscriptLine


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
        formatter: Union[LineFormatter, str] = "text",
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
