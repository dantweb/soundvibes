"""Audio device discovery, behind a backend seam so it is testable without hardware."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .config import CONFIG

#: Substrings identifying a loopback / virtual output-capture device.
LOOPBACK_HINTS = tuple(CONFIG.devices.loopback_hints)
MAX_CAPTURE_CHANNELS = CONFIG.audio.max_capture_channels


class DeviceResolutionError(RuntimeError):
    """A device selector matched nothing, or matched too much."""


def is_loopback_name(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in LOOPBACK_HINTS)


@dataclass(frozen=True)
class DeviceInfo:
    index: int | None
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool


class AudioBackend(Protocol):
    """The slice of an audio library soundvibes actually uses."""

    def query_devices(self) -> Sequence[Mapping[str, Any]]: ...

    def device_info(self, index: int | None) -> Mapping[str, Any]: ...

    def default_input_index(self) -> int | None: ...

    def open_input_stream(self, **kwargs: Any) -> Any: ...


class SoundDeviceBackend:
    """The real backend. sounddevice is imported lazily so that importing
    soundvibes on a machine without PortAudio still works."""

    def __init__(self) -> None:
        import sounddevice  # noqa: PLC0415 - deliberately deferred

        self._sounddevice = sounddevice

    def query_devices(self) -> Sequence[Mapping[str, Any]]:
        return self._sounddevice.query_devices()

    def device_info(self, index: int | None) -> Mapping[str, Any]:
        return self._sounddevice.query_devices(index, "input")

    def default_input_index(self) -> int | None:
        default_input, _ = self._sounddevice.default.device
        return default_input

    def open_input_stream(self, **kwargs: Any) -> Any:
        return self._sounddevice.InputStream(**kwargs)


class DeviceRegistry:
    """Resolves user-supplied device selectors into device indices."""

    def __init__(self, backend: AudioBackend) -> None:
        self._backend = backend

    def resolve(self, selector: str | None) -> int | None:
        """Turn an index or a partial, case-insensitive name into an index.

        None means "let the audio library pick the default input".
        """
        if selector is None:
            return None
        selector = selector.strip()
        if not selector:
            return None
        if selector.isdigit():
            return int(selector)

        wanted = selector.lower()
        matches = [
            index
            for index, device in enumerate(self._backend.query_devices())
            if self._can_capture(device) and wanted in device["name"].lower()
        ]

        if not matches:
            raise DeviceResolutionError(
                f"No input-capable device matches {selector!r}. "
                f"Run with --list-devices to see the options."
            )
        if len(matches) > 1:
            devices = self._backend.query_devices()
            listed = ", ".join(f"{index}:{devices[index]['name']}" for index in matches)
            raise DeviceResolutionError(f"{selector!r} is ambiguous, matches: {listed}")
        return matches[0]

    def find_loopback(self) -> int | None:
        """First input-capable device that looks like a loopback, if any."""
        for index, device in enumerate(self._backend.query_devices()):
            if self._can_capture(device) and is_loopback_name(device["name"]):
                return index
        return None

    def describe(self, index: int | None) -> DeviceInfo:
        if index is None:
            index = self._backend.default_input_index()
        device = self._backend.device_info(index)
        return DeviceInfo(
            index=index,
            name=device["name"],
            channels=min(MAX_CAPTURE_CHANNELS, int(device["max_input_channels"])),
            sample_rate=int(device["default_samplerate"]),
            is_loopback=is_loopback_name(device["name"]),
        )

    def format_table(self) -> str:
        """Render every capturable device. Returned, not printed, so it can be tested."""
        default_input = self._backend.default_input_index()
        rows = [f"{'idx':>4}  {'in':>3} {'out':>3}  {'rate':>7}  name", "-" * 78]
        for index, device in enumerate(self._backend.query_devices()):
            if not self._can_capture(device):
                continue
            marks = []
            if index == default_input:
                marks.append("default-input")
            if is_loopback_name(device["name"]):
                marks.append("loopback -> usable as SYS")
            suffix = f"   [{', '.join(marks)}]" if marks else ""
            rows.append(
                f"{index:>4}  {device['max_input_channels']:>3} "
                f"{device['max_output_channels']:>3}  "
                f"{int(device['default_samplerate']):>7}  {device['name']}{suffix}"
            )
        return "\n".join(rows)

    @staticmethod
    def _can_capture(device: Mapping[str, Any]) -> bool:
        return int(device["max_input_channels"]) > 0
