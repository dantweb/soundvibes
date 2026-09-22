"""Per-operating-system behaviour.

Two things genuinely differ between macOS and Linux: how you expose system
audio as a capture device, and which offline speech synthesiser exists for the
self-test. Everything else in soundvibes is portable.

Adding an OS means adding a class here and one line in `platform_for` — no
existing platform is touched.
"""

from __future__ import annotations

import sys
from typing import Protocol


class Platform(Protocol):
    name: str
    synthesis_binary: str

    def loopback_help(self) -> str:
        """Instructions shown when no loopback capture device was found."""

    def synthesis_command(self, text: str, output_path: str, language: str) -> list[str]:
        """Command that renders `text` to an audio file, for the self-test."""

    @property
    def synthesis_suffix(self) -> str:
        """File suffix the synthesiser writes."""


class MacOSPlatform:
    name = "macos"
    synthesis_binary = "say"
    synthesis_suffix = ".aiff"

    # `say` needs a voice per language; these ship with macOS.
    VOICES = {"en": "Samantha", "de": "Anna", "ru": "Milena"}

    def loopback_help(self) -> str:
        return """\
No loopback device found, so system audio (SYS) will NOT be captured.

macOS cannot record its own output without a virtual audio driver. To enable it:

    brew install blackhole-2ch          # then log out / restart audio

Then either
    * pick "BlackHole 2ch" as your system output (you stop hearing the sound), or
    * open "Audio MIDI Setup" -> + -> "Create Multi-Output Device", tick both your
      speakers and BlackHole 2ch, and select that as the system output
      (you keep hearing the sound - recommended).

soundvibes picks the loopback input up automatically on the next run, or pass it
explicitly with --system-device "BlackHole".
"""

    def synthesis_command(self, text: str, output_path: str, language: str) -> list[str]:
        voice = self.VOICES.get(language, "Samantha")
        return ["say", "-v", voice, "-o", output_path, text]


class LinuxPlatform:
    name = "linux"
    synthesis_binary = "espeak-ng"
    synthesis_suffix = ".wav"

    def loopback_help(self) -> str:
        return """\
No loopback device found, so system audio (SYS) will NOT be captured.

On Linux the output of a sink is already exposed as a ".monitor" source, but
PortAudio talks to ALSA, and the ALSA pulse plugin shows it one generic "pulse"
device rather than the individual sources. Point a named PCM at the monitor:

    PulseAudio / PipeWire (most desktops):
        pactl list short sources | grep monitor      # note the monitor's name

        # ~/.asoundrc  (or ~/.config/alsa/asoundrc)
        pcm.monitor {
          type pulse
          device "alsa_output.<your-sink>.monitor"   # the name from pactl
          hint { description "Monitor of the speakers" }
        }

        soundvibes --system-device monitor           # it now appears in --list-devices

    If pactl lists no monitor source at all, make sure the PulseAudio/PipeWire
    ALSA plugin is installed (Debian/Ubuntu: libasound2-plugins,
    pulseaudio-module-alsa; Fedora: alsa-plugins-pulseaudio).

    ALSA only, no sound server:
        load snd-aloop and capture from the loopback device, or route the
        application through it.

Microphone (MIC) capture works without any of this.
"""

    def synthesis_command(self, text: str, output_path: str, language: str) -> list[str]:
        return ["espeak-ng", "-v", language, "-w", output_path, text]


class GenericPlatform:
    """Fallback for anything not specifically supported (Windows, BSD, ...)."""

    name = "generic"
    synthesis_binary = "espeak-ng"
    synthesis_suffix = ".wav"

    def loopback_help(self) -> str:
        return """\
No loopback device found, so system audio (SYS) will NOT be captured.

Capturing what the machine plays needs a loopback (virtual) input device that
mirrors your output. Install one for your system - "Stereo Mix", VB-Cable and
similar all work - then re-run with --list-devices and pass it explicitly:

    soundvibes --system-device "<device name>"

Microphone (MIC) capture works without any of this.
"""

    def synthesis_command(self, text: str, output_path: str, language: str) -> list[str]:
        return ["espeak-ng", "-v", language, "-w", output_path, text]


_PLATFORMS = {"darwin": MacOSPlatform, "linux": LinuxPlatform}


def platform_for(system: str | None = None) -> Platform:
    """Pick the platform implementation for `system` (defaults to this machine)."""
    system = (system if system is not None else sys.platform).lower()
    for prefix, implementation in _PLATFORMS.items():
        if system.startswith(prefix):
            return implementation()
    return GenericPlatform()
