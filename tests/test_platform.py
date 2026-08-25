"""Platform-specific guidance. macOS and Linux capture system audio differently."""
from soundvibes.platforms import (LinuxPlatform, MacOSPlatform, GenericPlatform,
                                  platform_for)


class TestPlatformSelection:
    def test_darwin_selects_macos(self):
        assert isinstance(platform_for("darwin"), MacOSPlatform)

    def test_linux_selects_linux(self):
        assert isinstance(platform_for("linux"), LinuxPlatform)

    def test_unknown_falls_back_to_generic(self):
        assert isinstance(platform_for("win32"), GenericPlatform)


class TestLoopbackGuidance:
    def test_macos_recommends_blackhole_and_multi_output(self):
        help_text = MacOSPlatform().loopback_help()
        assert "blackhole" in help_text.lower()
        assert "Multi-Output" in help_text
        assert "pactl" not in help_text  # no Linux advice on a Mac

    def test_linux_recommends_a_monitor_source(self):
        help_text = LinuxPlatform().loopback_help()
        lowered = help_text.lower()
        assert "monitor" in lowered
        assert "pulseaudio" in lowered or "pipewire" in lowered
        assert "blackhole" not in lowered  # no macOS advice on Linux

    def test_generic_still_explains_the_concept(self):
        assert "loopback" in GenericPlatform().loopback_help().lower()


class TestSpeechSynthesis:
    """The self-test needs offline TTS; the binary differs per platform."""

    def test_macos_uses_say(self):
        assert MacOSPlatform().synthesis_command("hello", "out.wav", "en")[0] == "say"

    def test_linux_uses_espeak(self):
        assert LinuxPlatform().synthesis_command("hello", "out.wav", "en")[0] == "espeak-ng"

    def test_each_platform_names_its_required_binary(self):
        assert MacOSPlatform().synthesis_binary == "say"
        assert LinuxPlatform().synthesis_binary == "espeak-ng"
