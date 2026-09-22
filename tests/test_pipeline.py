"""The pipeline: one place that turns utterances into written lines.

Previously this logic existed twice — once in the main loop and once in the
shutdown drain — so a fix to one could silently miss the other.
"""

import datetime as dt
import queue

import numpy as np
from conftest import FakeEngine, make_result

from soundvibes.constants import SAMPLE_RATE
from soundvibes.models import Utterance
from soundvibes.pipeline import TranscriptionPipeline
from soundvibes.transcription import TranscriptionService


class RecordingWriter:
    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, line):
        rendered = f"[{line.source}] {line.text}"
        self.written.append(rendered)
        return rendered

    def close(self):
        self.closed = True


def utterance(source="MIC"):
    return Utterance(source, np.zeros(SAMPLE_RATE, dtype=np.float32), dt.datetime.now())


def build(results, echo=None):
    service = TranscriptionService(FakeEngine(results), ["en", "de"], beam_size=5)
    writer = RecordingWriter()
    return TranscriptionPipeline(service, writer, on_line=echo), writer


class TestProcess:
    def test_transcribed_utterance_is_written(self):
        pipeline, writer = build([make_result("hello there")])

        rendered = pipeline.process(utterance())

        assert rendered == "[MIC] hello there"
        assert writer.written == ["[MIC] hello there"]

    def test_empty_transcription_writes_nothing(self):
        pipeline, writer = build([make_result("Thank you.")])

        assert pipeline.process(utterance()) is None
        assert writer.written == []

    def test_lines_written_is_counted(self):
        pipeline, _ = build([make_result("one"), make_result("Thank you."), make_result("two")])

        for _ in range(3):
            pipeline.process(utterance())

        assert pipeline.lines_written == 2

    def test_echo_callback_receives_rendered_lines_only(self):
        echoed = []
        pipeline, _ = build([make_result("spoken"), make_result("Thank you.")], echo=echoed.append)

        pipeline.process(utterance())
        pipeline.process(utterance())

        assert echoed == ["[MIC] spoken"]

    def test_a_failing_utterance_does_not_kill_the_run(self):
        """One bad utterance must not end a long recording session."""

        class ExplodingService:
            def transcribe(self, _utterance):
                raise RuntimeError("engine blew up")

        writer = RecordingWriter()
        pipeline = TranscriptionPipeline(ExplodingService(), writer)

        assert pipeline.process(utterance()) is None
        assert pipeline.errors == 1


class TestDrain:
    def test_everything_queued_is_processed(self):
        pipeline, writer = build([make_result("one"), make_result("two")])
        pending = queue.Queue()
        pending.put(utterance())
        pending.put(utterance())

        drained = pipeline.drain(pending)

        assert drained == 2
        assert len(writer.written) == 2

    def test_draining_an_empty_queue_is_a_no_op(self):
        pipeline, _ = build([])
        assert pipeline.drain(queue.Queue()) == 0

    def test_drain_uses_the_same_path_as_process(self):
        """Shutdown must not have its own copy of the filtering rules."""
        pipeline, writer = build([make_result("Thank you."), make_result("real")])
        pending = queue.Queue()
        pending.put(utterance())
        pending.put(utterance())

        pipeline.drain(pending)

        assert writer.written == ["[MIC] real"]
