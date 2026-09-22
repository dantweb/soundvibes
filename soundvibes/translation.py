"""Translation backends, behind one narrow seam.

soundvibes transcribes locally and nothing leaves the machine. Translation is
the first feature where that can stop being true, so the choice is explicit:

  * ``argos``  - fully offline neural translation. Preserves the guarantee, at
                 the cost of an extra dependency and language packages that are
                 downloaded once.
  * ``claude`` - the Anthropic API. Better quality, no local install, but your
                 transcript text is sent to a third party. Never the default.
  * ``none``   - passthrough, used when translation is switched off.

A backend is a class with one method. Adding one is `register_translator`.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from .config import CONFIG

_DEFAULTS = CONFIG.translation

MAX_CACHE_ENTRIES = _DEFAULTS.cache_entries
FILE_PREFIX = _DEFAULTS.file_prefix

_LANGUAGE_SEPARATORS = re.compile(r"[-_]")


class TranslationError(RuntimeError):
    """A backend could not translate — missing dependency, model or network."""


class TranslatorUnavailable(TranslationError):
    """The backend cannot work at all in this run: a dependency is missing.

    Distinct from a per-line failure so the writer can report it once and stop
    asking, instead of repeating the same install hint for every utterance.
    """


def normalise_language(code: str) -> str:
    """'RU' / 'en-US' / ' Fr ' -> 'ru' / 'en' / 'fr'."""
    return _LANGUAGE_SEPARATORS.split(code.strip().lower())[0]


class Translator(Protocol):
    def translate(self, text: str, source_language: str, target_language: str) -> str: ...


class IdentityTranslator:
    """Returns the text unchanged. Used when translation is switched off."""

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        return text


class CachingTranslator:
    """Remembers recent translations.

    Live conversation is repetitive — "yes", "okay", "one moment" recur
    constantly — and every repeat is otherwise a fresh model call or API round
    trip. Bounded so a long session cannot grow without limit.
    """

    def __init__(self, inner: Translator, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self._inner = inner
        self._max_entries = max_entries
        self._cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        key = (text, source_language, target_language)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        translated = self._inner.translate(text, source_language, target_language)
        self._cache[key] = translated
        if len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)
        return translated


class _DropStanzaDefaultsNotice(logging.Filter):
    """Drops 'Language en package default expects mwt, which has been added'."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "expects mwt" not in record.getMessage()


def quiet_argos_dependencies() -> None:
    """Stop stanza logging 'Language en package default expects mwt, which has
    been added' at WARNING level on every single translation. It is stanza
    telling itself about its own defaults; nothing the user can act on.

    A filter rather than a level: argos constructs stanza's Pipeline with its
    own logging_level, which resets whatever level was set on the logger.
    """
    logger = logging.getLogger("stanza")
    if not any(isinstance(f, _DropStanzaDefaultsNotice) for f in logger.filters):
        logger.addFilter(_DropStanzaDefaultsNotice())


def _import_argos():
    """Isolated so the missing-dependency path is testable."""
    import argostranslate.package  # noqa: PLC0415
    import argostranslate.translate  # noqa: PLC0415

    quiet_argos_dependencies()
    return argostranslate.package, argostranslate.translate


class ArgosTranslator:
    """Offline translation via Argos Translate.

    Language pairs are downloaded on first use, the same way the whisper model
    is. After that it runs with no network at all.
    """

    def __init__(self, auto_install: bool = True) -> None:
        self._auto_install = auto_install
        self._installed_pairs: set[tuple[str, str]] = set()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        package_api, translate_api = self._modules()
        source = normalise_language(source_language)
        target = normalise_language(target_language)
        if self._auto_install:
            self._ensure_pair(package_api, source, target)
        try:
            return translate_api.translate(text, source, target)
        except Exception as error:  # noqa: BLE001 - surfaced as our own error type
            raise TranslationError(
                f"argos could not translate {source}->{target}: {error}"
            ) from error

    def _modules(self):
        try:
            return _import_argos()
        except ImportError as error:
            raise TranslatorUnavailable(
                "Offline translation needs Argos Translate, which is not installed:\n"
                "    make install offline\n"
                "Or choose another backend with --translator claude."
            ) from error

    def _ensure_pair(self, package_api, source: str, target: str) -> None:
        if (source, target) in self._installed_pairs:
            return
        try:
            available = package_api.get_installed_packages()
            if not any(p.from_code == source and p.to_code == target for p in available):
                package_api.update_package_index()
                candidates = package_api.get_available_packages()
                match = next(
                    (p for p in candidates if p.from_code == source and p.to_code == target), None
                )
                if match is None:
                    # No direct package. Argos pivots through English when the
                    # legs are installed, so let the translation attempt decide
                    # rather than refusing here.
                    self._installed_pairs.add((source, target))
                    return
                package_api.install_from_path(match.download())
        except TranslationError:
            raise
        except Exception as error:  # noqa: BLE001
            raise TranslationError(
                f"could not install the argos {source}->{target} package: {error}"
            ) from error
        self._installed_pairs.add((source, target))


class ClaudeTranslator:
    """Translation via the Anthropic API.

    Note what this costs you: the transcript text leaves the machine. Only use
    it where that is acceptable.
    """

    SCHEMA = {
        "type": "object",
        "properties": {"translation": {"type": "string"}},
        "required": ["translation"],
        "additionalProperties": False,
    }

    SYSTEM = (
        "You translate short fragments of transcribed speech. Return only the "
        "translation, preserving tone and register. Speech is disfluent and "
        "sometimes clipped mid-sentence; translate what is there rather than "
        "completing it. If the fragment is already in the target language, "
        "return it unchanged."
    )

    def __init__(
        self,
        model: str = _DEFAULTS.claude.model,
        effort: str = _DEFAULTS.claude.effort,
        max_tokens: int = _DEFAULTS.claude.max_tokens,
    ) -> None:
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._client = None

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        client = self._ensure_client()
        target = normalise_language(target_language)
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self.SYSTEM,
                messages=[{"role": "user", "content": f"Translate into {target}:\n\n{text}"}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": self.SCHEMA},
                },
            )
        except Exception as error:  # noqa: BLE001
            raise TranslationError(f"Anthropic API call failed: {error}") from error

        if response.stop_reason == "refusal":
            raise TranslationError("Claude declined to translate this fragment.")

        import json  # noqa: PLC0415

        body = next((block.text for block in response.content if block.type == "text"), "")
        return json.loads(body)["translation"]

    def _ensure_client(self):
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as error:
                raise TranslatorUnavailable(
                    "The claude backend needs the Anthropic SDK:\n    pip install anthropic"
                ) from error
            self._client = anthropic.Anthropic()
        return self._client


_TRANSLATORS: dict[str, Callable[[], Translator]] = {
    "none": IdentityTranslator,
    "argos": ArgosTranslator,
    "claude": ClaudeTranslator,
}


def register_translator(name: str, factory: Callable[[], Translator] | None) -> None:
    """Add a backend, or remove one by passing None."""
    if factory is None:
        _TRANSLATORS.pop(name, None)
    else:
        _TRANSLATORS[name] = factory


def available_translators() -> list[str]:
    return sorted(_TRANSLATORS)


def create_translator(name: str) -> Translator:
    try:
        return _TRANSLATORS[name]()
    except KeyError:
        raise ValueError(
            f"Unknown translation backend {name!r}. Available: {', '.join(available_translators())}"
        ) from None
