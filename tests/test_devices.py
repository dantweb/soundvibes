"""Device discovery against a fake backend — no sounddevice, no hardware."""
import pytest

from conftest import FakeAudioBackend
from soundvibes.config import CONFIG
from soundvibes.devices import DeviceRegistry, DeviceResolutionError, is_loopback_name


class TestLoopbackNaming:
    # The hint list is config.yaml's, so assert each configured hint is
    # honoured rather than pinning a copy of today's list.
    @pytest.mark.parametrize("hint", list(CONFIG.devices.loopback_hints))
    def test_every_configured_hint_is_recognised(self, hint):
        assert is_loopback_name(f"Some {hint.title()} Device")

    @pytest.mark.parametrize("name", [
        "MacBook Pro Microphone", "External Headphones", "USB Audio Device",
    ])
    def test_ordinary_devices_are_not_loopback(self, name):
        assert not is_loopback_name(name)


class TestDeviceRegistry:
    def test_none_resolves_to_the_default(self, backend):
        assert DeviceRegistry(backend).resolve(None) is None

    def test_numeric_index_is_used_directly(self, backend):
        assert DeviceRegistry(backend).resolve("2") == 2

    def test_partial_name_is_matched_case_insensitively(self, backend):
        assert DeviceRegistry(backend).resolve("blackhole") == 2

    def test_whitespace_is_ignored(self, backend):
        assert DeviceRegistry(backend).resolve("  blackhole  ") == 2

    def test_unmatched_name_is_an_error_naming_the_remedy(self, backend):
        with pytest.raises(DeviceResolutionError, match="--list-devices"):
            DeviceRegistry(backend).resolve("does-not-exist")

    def test_ambiguous_name_lists_the_candidates(self, backend):
        with pytest.raises(DeviceResolutionError, match="ambiguous"):
            DeviceRegistry(backend).resolve("microphone")

    def test_output_only_devices_are_never_matched(self, backend):
        with pytest.raises(DeviceResolutionError):
            DeviceRegistry(backend).resolve("External Headphones")

    def test_loopback_is_autodetected(self, backend):
        assert DeviceRegistry(backend).find_loopback() == 2

    def test_absent_loopback_reports_none(self):
        backend = FakeAudioBackend(devices=[
            {"name": "MacBook Pro Microphone", "max_input_channels": 1,
             "max_output_channels": 0, "default_samplerate": 48000},
        ])
        assert DeviceRegistry(backend).find_loopback() is None

    def test_describe_reports_name_channels_and_rate(self, backend):
        info = DeviceRegistry(backend).describe(2)
        assert info.name == "BlackHole 2ch"
        assert info.channels == 2
        assert info.sample_rate == 48000

    def test_describe_caps_channels_at_stereo(self):
        backend = FakeAudioBackend(devices=[
            {"name": "Interface", "max_input_channels": 8,
             "max_output_channels": 0, "default_samplerate": 48000},
        ])
        assert DeviceRegistry(backend).describe(0).channels == 2

    def test_table_is_returned_as_text_not_printed(self, backend):
        """Returning the table instead of printing it makes it assertable."""
        table = DeviceRegistry(backend).format_table()

        assert "BlackHole 2ch" in table
        assert "loopback" in table
        assert "default-input" in table
        assert "External Headphones" not in table  # no input channels
