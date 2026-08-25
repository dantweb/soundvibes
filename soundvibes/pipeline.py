"""Utterances in, transcript lines out.

One implementation used by both the live loop and the shutdown drain. They were
separate copies before, so a change to the live path could silently miss the
audio still queued when you pressed Ctrl-C.
"""
from __future__ import annotations

import queue
import sys
import threading
from typing import Callable, Optional, Sequence

from .models import TranscriptLine, Utterance

#: how long the live loop waits for an utterance before re-checking the sources
POLL_SECONDS = 0.25


class TranscriptionPipeline:
    def __init__(self, service, writer, on_line: Optional[Callable[[str], None]] = None) -> None:
        self._service = service
        self._writer = writer
        self._on_line = on_line
        self.lines_written = 0
        self.errors = 0

    def process(self, utterance: Utterance) -> Optional[str]:
        """Transcribe and write one utterance. Returns the rendered line, if any."""
        try:
            line = self._service.transcribe(utterance)
        except Exception as error:  # noqa: BLE001 - one bad utterance must not end the session
            self.errors += 1
            print(f"[{utterance.source}] transcription failed: {error}", file=sys.stderr)
            return None

        if line is None:
            return None

        rendered = self._writer.write(line)
        self.lines_written += 1
        if self._on_line is not None:
            self._on_line(rendered)
        return rendered

    def drain(self, pending: "queue.Queue[Utterance]") -> int:
        """Process everything already queued. Used on shutdown."""
        processed = 0
        while True:
            try:
                utterance = pending.get_nowait()
            except queue.Empty:
                return processed
            self.process(utterance)
            processed += 1

    def run(self, pending: "queue.Queue[Utterance]", sources: Sequence,
            stop_event: threading.Event) -> None:
        """Consume utterances until every source has stopped, or we are asked to."""
        while True:
            try:
                utterance = pending.get(timeout=POLL_SECONDS)
            except queue.Empty:
                if any(source.is_alive() for source in sources):
                    continue
                if not stop_event.is_set():
                    print("All capture sources stopped, exiting. On macOS check "
                          "System Settings > Privacy & Security > Microphone; on "
                          "Linux check that your user can read the capture device.",
                          file=sys.stderr)
                return
            self.process(utterance)
