"""Loads config.yaml — the single source of every tunable value.

The modules in this package do not carry their own defaults; they read from
here. That is the point: one file to look in, and no chance of a literal in the
source disagreeing with the documented value.

Resolution order:
    1. $SOUNDVIBES_CONFIG
    2. ./config.yaml in the working directory
    3. the copy that ships alongside the package
    4. config.yaml.dist - the full template, as a last resort if config.yaml
       was deleted
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
SEARCH_PATHS = (
    Path.cwd() / "config.yaml",
    PACKAGE_ROOT.parent / "config.yaml",
    PACKAGE_ROOT / "config.yaml",
    Path.cwd() / "config.yaml.dist",
    PACKAGE_ROOT.parent / "config.yaml.dist",
)


class ConfigError(RuntimeError):
    """The configuration file is missing, malformed, or lacks a required key."""


class Section:
    """Dot-accessible view over a nested mapping, with errors that name the key."""

    def __init__(self, values: dict, path: str = "") -> None:
        self._values = values
        self._path = path

    def __getattr__(self, name: str) -> Any:
        try:
            value = self._values[name]
        except KeyError:
            location = f"{self._path}.{name}" if self._path else name
            raise ConfigError(f"missing key {location!r} in config.yaml") from None
        if isinstance(value, dict):
            return Section(value, f"{self._path}.{name}" if self._path else name)
        return value

    def get(self, name: str, default: Any = None) -> Any:
        return self._values.get(name, default)

    def __contains__(self, name: str) -> bool:
        return name in self._values

    def __repr__(self) -> str:
        return f"Section({self._path or 'root'}: {sorted(self._values)})"


def find_config_file() -> Path:
    override = os.environ.get("SOUNDVIBES_CONFIG")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ConfigError(f"SOUNDVIBES_CONFIG points at {path}, which does not exist")
        return path
    for candidate in SEARCH_PATHS:
        if candidate.is_file():
            return candidate
    raise ConfigError(
        "config.yaml not found. Looked in: " + ", ".join(str(path) for path in SEARCH_PATHS)
    )


def load_config(path: Path | None = None) -> Section:
    path = Path(path) if path is not None else find_config_file()
    try:
        values = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(values, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return Section(values)


#: Loaded once at import. Modules read their values from this.
CONFIG = load_config()
