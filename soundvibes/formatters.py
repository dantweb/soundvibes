"""Transcript line formats, as interchangeable strategies.

A new format is a class plus one `register_formatter` call — no existing code
is edited, which is the point.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Protocol

from .models import TranscriptLine


class LineFormatter(Protocol):
    def format(self, line: TranscriptLine) -> str: ...

    def header(self, moment: dt.datetime) -> str | None:
        """Text written once when a transcript file is opened, if any."""


class TextFormatter:
    """Human-readable: [13:41:39] [MIC] [de] Guten Tag."""

    def format(self, line: TranscriptLine) -> str:
        clock = line.started_at.strftime("%H:%M:%S")
        return f"[{clock}] [{line.source}] [{line.language}] {line.text}"

    def header(self, moment: dt.datetime) -> str | None:
        stamp = moment.strftime("%Y-%m-%d %H:%M:%S")
        return f"\n===== soundvibes session started {stamp} ====="


class JsonlFormatter:
    """One JSON object per line, for downstream processing."""

    def format(self, line: TranscriptLine) -> str:
        return json.dumps(
            {
                "timestamp": line.started_at.isoformat(timespec="seconds"),
                "source": line.source,
                "language": line.language,
                "language_probability": round(line.language_probability, 3),
                "duration_seconds": round(line.duration_seconds, 2),
                "text": line.text,
            },
            ensure_ascii=False,
        )

    def header(self, moment: dt.datetime) -> str | None:
        return None  # a header would break line-per-object parsing


_FORMATTERS: dict[str, Callable[[], LineFormatter]] = {
    "text": TextFormatter,
    "jsonl": JsonlFormatter,
}


def register_formatter(name: str, factory: Callable[[], LineFormatter] | None) -> None:
    """Add a format, or remove one by passing None."""
    if factory is None:
        _FORMATTERS.pop(name, None)
    else:
        _FORMATTERS[name] = factory


def available_formats() -> list[str]:
    return sorted(_FORMATTERS)


def create_formatter(name: str) -> LineFormatter:
    try:
        return _FORMATTERS[name]()
    except KeyError:
        raise ValueError(
            f"Unknown transcript format {name!r}. Available: {', '.join(available_formats())}"
        ) from None
