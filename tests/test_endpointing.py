"""The energy endpointer: the one piece of real signal processing we own."""

import numpy as np
from conftest import silence, tone

from soundvibes.constants import FRAME_SAMPLES, SAMPLE_RATE
from soundvibes.endpointing import SpeechEndpointer


def feed(endpointer, samples):
    """Push a signal frame by frame, collecting whatever utterances fall out."""
    finished = []
    usable = len(samples) - (len(samples) % FRAME_SAMPLES)
    for start in range(0, usable, FRAME_SAMPLES):
        result = endpointer.push(samples[start : start + FRAME_SAMPLES])
        if result is not None:
            finished.append(result)
    return finished


def make(**overrides):
    settings = dict(silence_seconds=0.7, min_speech_seconds=0.4, max_speech_seconds=20.0)
    settings.update(overrides)
    return SpeechEndpointer(**settings)


def test_silence_alone_produces_nothing():
    assert feed(make(), silence(3.0)) == []


def test_speech_between_silences_is_one_utterance():
    signal = np.concatenate([silence(1.0), tone(1.5), silence(1.5)])
    finished = feed(make(), signal)

    assert len(finished) == 1
    audio, started_at = finished[0]
    assert audio.dtype == np.float32
    assert started_at is not None
    # Roughly the speech, plus pre-roll and the trailing silence that closed it.
    assert 1.5 <= len(audio) / SAMPLE_RATE <= 3.0


def test_two_separated_utterances_are_split():
    signal = np.concatenate(
        [
            silence(1.0),
            tone(1.0),
            silence(1.5),
            tone(1.0),
            silence(1.5),
        ]
    )
    assert len(feed(make(), signal)) == 2


def test_short_blip_is_discarded():
    # Below min_speech_seconds, so it must not reach the transcriber.
    signal = np.concatenate([silence(1.0), tone(0.15), silence(1.5)])
    assert feed(make(min_speech_seconds=0.4), signal) == []


def test_overlong_speech_is_force_split():
    signal = np.concatenate([silence(0.5), tone(5.0)])
    finished = feed(make(max_speech_seconds=2.0), signal)

    assert len(finished) >= 2
    # A forced split keeps its audio even though no silence ended it.
    assert all(len(audio) > 0 for audio, _ in finished)


def test_preroll_keeps_the_leading_consonant():
    """The utterance must start slightly before speech was detected."""
    without_preroll = make(preroll_seconds=0.0)
    with_preroll = make(preroll_seconds=0.32)
    signal = np.concatenate([silence(1.0), tone(1.0), silence(1.5)])

    short = feed(without_preroll, signal)[0][0]
    long = feed(with_preroll, signal)[0][0]

    assert len(long) > len(short)


def test_flush_returns_speech_in_progress():
    endpointer = make()
    feed(endpointer, np.concatenate([silence(1.0), tone(1.0)]))

    flushed = endpointer.flush()

    assert flushed is not None
    audio, _ = flushed
    assert len(audio) > 0


def test_flush_on_idle_returns_nothing():
    endpointer = make()
    feed(endpointer, silence(1.0))
    assert endpointer.flush() is None


def test_loud_room_does_not_trigger_constantly():
    """The noise floor adapts, so steady background noise is not speech."""
    noise = (np.random.default_rng(7).normal(0, 0.02, SAMPLE_RATE * 3)).astype(np.float32)
    assert feed(make(), noise) == []


def test_sensitivity_controls_the_threshold():
    quiet_speech = np.concatenate([silence(1.0), tone(1.0, amplitude=0.02), silence(1.5)])

    insensitive = feed(make(sensitivity=8.0), quiet_speech)
    sensitive = feed(make(sensitivity=1.5), quiet_speech)

    assert len(sensitive) >= len(insensitive)
