"""Translation is a seam, like the transcription engine — backends are adapters."""
import pytest

from soundvibes.translation import (CachingTranslator, IdentityTranslator,
                                    TranslationError, available_translators,
                                    create_translator, normalise_language,
                                    register_translator)


class RecordingTranslator:
    """Uppercases the text so a translation is visibly distinct from the original."""

    def __init__(self):
        self.calls = []

    def translate(self, text, source_language, target_language):
        self.calls.append((text, source_language, target_language))
        return f"[{target_language}] {text.upper()}"


class TestIdentityTranslator:
    def test_returns_the_text_untouched(self):
        assert IdentityTranslator().translate("hallo", "de", "en") == "hallo"


class TestNormaliseLanguage:
    @pytest.mark.parametrize("given,expected", [
        ("RU", "ru"), ("ru", "ru"), (" Fr ", "fr"), ("en-US", "en"), ("PT_BR", "pt"),
    ])
    def test_codes_are_reduced_to_a_bare_lowercase_code(self, given, expected):
        assert normalise_language(given) == expected


class TestCachingTranslator:
    def test_repeated_text_is_translated_once(self):
        inner = RecordingTranslator()
        translator = CachingTranslator(inner)

        first = translator.translate("yes", "en", "ru")
        second = translator.translate("yes", "en", "ru")

        assert first == second
        assert len(inner.calls) == 1

    def test_different_targets_are_cached_separately(self):
        inner = RecordingTranslator()
        translator = CachingTranslator(inner)

        translator.translate("yes", "en", "ru")
        translator.translate("yes", "en", "fr")

        assert len(inner.calls) == 2

    def test_cache_is_bounded(self):
        inner = RecordingTranslator()
        translator = CachingTranslator(inner, max_entries=2)

        for text in ("one", "two", "three"):
            translator.translate(text, "en", "ru")
        translator.translate("one", "en", "ru")  # evicted, so translated again

        assert len(inner.calls) == 4


class TestRegistry:
    def test_builtin_backends_are_listed(self):
        assert set(available_translators()) >= {"argos", "claude", "none"}

    def test_none_creates_the_identity_translator(self):
        assert isinstance(create_translator("none"), IdentityTranslator)

    def test_unknown_backend_names_the_alternatives(self):
        with pytest.raises(ValueError, match="argos"):
            create_translator("babelfish")

    def test_a_new_backend_needs_no_change_to_existing_code(self):
        register_translator("recording", RecordingTranslator)
        try:
            assert "recording" in available_translators()
            assert create_translator("recording").translate("hi", "en", "ru") == "[ru] HI"
        finally:
            register_translator("recording", None)


class TestBackendsFailLoudlyWhenUnavailable:
    def test_argos_explains_how_to_install_it(self, monkeypatch):
        """The offline backend is an optional dependency; the error must say so."""
        from soundvibes import translation

        monkeypatch.setattr(translation, "_import_argos", _raise_import)
        with pytest.raises(TranslationError, match="pip install"):
            translation.ArgosTranslator().translate("hallo", "de", "en")


def _raise_import():
    raise ImportError("no module named argostranslate")
