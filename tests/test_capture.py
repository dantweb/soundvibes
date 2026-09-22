"""Audio preprocessing and framing — pure, so no device is involved."""

import numpy as np

from soundvibes.capture import AudioPreprocessor, FrameSplitter
from soundvibes.constants import FRAME_SAMPLES, SAMPLE_RATE


class TestFrameSplitter:
    def test_exact_multiple_yields_whole_frames(self):
        splitter = FrameSplitter()
        frames = splitter.push(np.zeros(FRAME_SAMPLES * 3, dtype=np.float32))
        assert len(frames) == 3
        assert all(len(frame) == FRAME_SAMPLES for frame in frames)

    def test_remainder_is_carried_into_the_next_push(self):
        splitter = FrameSplitter()

        first = splitter.push(np.zeros(FRAME_SAMPLES + 10, dtype=np.float32))
        second = splitter.push(np.zeros(FRAME_SAMPLES - 10, dtype=np.float32))

        assert len(first) == 1
        assert len(second) == 1  # the 10 leftover samples completed this frame

    def test_no_samples_are_lost_across_pushes(self):
        splitter = FrameSplitter()
        signal = np.arange(FRAME_SAMPLES * 2 + 7, dtype=np.float32)

        frames = splitter.push(signal[:100]) + splitter.push(signal[100:])
        rebuilt = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)

        assert np.array_equal(rebuilt, signal[: len(rebuilt)])
        assert len(rebuilt) == FRAME_SAMPLES * 2

    def test_short_push_yields_nothing_yet(self):
        assert FrameSplitter().push(np.zeros(5, dtype=np.float32)) == []


class TestAudioPreprocessor:
    def test_stereo_is_averaged_to_mono(self):
        preprocessor = AudioPreprocessor(source_rate=SAMPLE_RATE)
        stereo = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

        mono = preprocessor.process(stereo)

        assert mono.ndim == 1
        assert np.allclose(mono, [0.5, 0.5])

    def test_mono_passes_through_unchanged(self):
        preprocessor = AudioPreprocessor(source_rate=SAMPLE_RATE)
        signal = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        assert np.allclose(preprocessor.process(signal), signal)

    def test_gain_is_applied(self):
        preprocessor = AudioPreprocessor(source_rate=SAMPLE_RATE, gain=2.0)
        signal = np.array([0.1, 0.2], dtype=np.float32)
        assert np.allclose(preprocessor.process(signal), [0.2, 0.4])

    def test_resamples_to_the_whisper_rate(self):
        preprocessor = AudioPreprocessor(source_rate=48_000)
        one_second = np.zeros(48_000, dtype=np.float32)

        resampled = preprocessor.process(one_second)

        assert abs(len(resampled) - SAMPLE_RATE) < 100

    def test_matching_rate_skips_resampling(self):
        preprocessor = AudioPreprocessor(source_rate=SAMPLE_RATE)
        signal = np.zeros(1000, dtype=np.float32)
        assert len(preprocessor.process(signal)) == 1000

    def test_output_is_always_float32(self):
        preprocessor = AudioPreprocessor(source_rate=44_100)
        assert preprocessor.process(np.zeros(4410, dtype=np.float64)).dtype == np.float32
