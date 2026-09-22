"""BackgroundWriter: slow writers (translation) run on their own thread."""

import datetime as dt
import threading

from soundvibes.models import TranscriptLine
from soundvibes.writer import BackgroundWriter


def line(text="Guten Tag.", language="de"):
    return TranscriptLine(
        source="MIC",
        language=language,
        text=text,
        started_at=dt.datetime(2026, 8, 25, 13, 41, 39),
        duration_seconds=1.0,
        language_probability=0.9,
    )


class RecordingWriter:
    def __init__(self, gate: threading.Event | None = None, failing_texts=()):
        self.written = []
        self.closed = False
        self._gate = gate
        self._failing = set(failing_texts)

    def write(self, line):
        if self._gate is not None:
            self._gate.wait(timeout=5)
        if line.text in self._failing:
            raise RuntimeError(f"cannot handle {line.text!r}")
        self.written.append(line.text)
        return line.text

    def close(self):
        self.closed = True


def test_write_returns_before_the_wrapped_writer_has_run():
    gate = threading.Event()  # the inner writer blocks until we release it
    inner = RecordingWriter(gate=gate)
    writer = BackgroundWriter(inner)

    returned = writer.write(line("Guten Tag."))

    assert returned == "Guten Tag."
    assert inner.written == []  # still blocked: write did not wait for it
    gate.set()
    writer.close()
    assert inner.written == ["Guten Tag."]


def test_lines_reach_the_wrapped_writer_in_order():
    inner = RecordingWriter()
    writer = BackgroundWriter(inner)

    for text in ("eins", "zwei", "drei"):
        writer.write(line(text))
    writer.close()

    assert inner.written == ["eins", "zwei", "drei"]


def test_close_finishes_the_backlog_then_closes_the_wrapped_writer():
    gate = threading.Event()
    inner = RecordingWriter(gate=gate)
    writer = BackgroundWriter(inner)
    for text in ("eins", "zwei", "drei"):
        writer.write(line(text))
    assert writer.pending >= 2  # the first may already be blocked inside write()

    gate.set()
    writer.close()

    assert inner.written == ["eins", "zwei", "drei"]
    assert inner.closed
    assert writer.pending == 0


def test_close_announces_a_backlog():
    gate = threading.Event()
    announced = []
    writer = BackgroundWriter(
        RecordingWriter(gate=gate), name="translation", announce=announced.append
    )
    writer.write(line("eins"))
    writer.write(line("zwei"))

    gate.set()
    writer.close()

    assert announced and "translation" in announced[0]


def test_no_announcement_without_a_backlog():
    announced = []
    writer = BackgroundWriter(RecordingWriter(), announce=announced.append)
    writer.close()
    assert announced == []


def test_one_failing_line_does_not_stop_the_worker(capsys):
    inner = RecordingWriter(failing_texts={"zwei"})
    writer = BackgroundWriter(inner, name="translation")

    for text in ("eins", "zwei", "drei"):
        writer.write(line(text))
    writer.close()

    assert inner.written == ["eins", "drei"]
    assert writer.errors == 1
    assert "[translation] cannot handle 'zwei'" in capsys.readouterr().err


class TestPrepare:
    """Model warm-up runs on the worker before the first line, never on the caller."""

    def test_prepare_runs_before_any_line_and_off_the_calling_thread(self):
        events = []
        inner = RecordingWriter()

        def prepare():
            events.append(("prepare", threading.current_thread().name))

        writer = BackgroundWriter(inner, name="translation", prepare=prepare)
        writer.write(line("eins"))
        writer.close()

        assert events == [("prepare", "translation-writer")]
        assert inner.written == ["eins"]

    def test_ready_is_set_once_prepare_has_finished(self):
        gate = threading.Event()
        writer = BackgroundWriter(RecordingWriter(), prepare=lambda: gate.wait(timeout=5))

        assert not writer.ready.is_set()
        gate.set()
        assert writer.ready.wait(timeout=5)
        writer.close()

    def test_a_failing_prepare_is_reported_and_lines_still_flow(self, capsys):
        def prepare():
            raise RuntimeError("no model")

        inner = RecordingWriter()
        writer = BackgroundWriter(inner, name="translation", prepare=prepare)
        writer.write(line("eins"))
        writer.close()

        assert inner.written == ["eins"]
        assert writer.errors == 1
        assert "[translation] warm-up failed: no model" in capsys.readouterr().err
