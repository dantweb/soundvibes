"""Translation is a seam, like the transcription engine — backends are adapters."""

import pytest

from soundvibes.translation import (
    CachingTranslator,
    IdentityTranslator,
    TranslationError,
    available_translators,
    create_translator,
    normalise_language,
    register_translator,
)


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
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("RU", "ru"),
            ("ru", "ru"),
            (" Fr ", "fr"),
            ("en-US", "en"),
            ("PT_BR", "pt"),
        ],
    )
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
        with pytest.raises(translation.TranslatorUnavailable, match="make install offline"):
            translation.ArgosTranslator().translate("hallo", "de", "en")

    def test_a_missing_dependency_is_still_a_translation_error(self, monkeypatch):
        """Callers that only know TranslationError keep working."""
        from soundvibes import translation

        monkeypatch.setattr(translation, "_import_argos", _raise_import)
        with pytest.raises(TranslationError):
            translation.ArgosTranslator().translate("hallo", "de", "en")


def _raise_import():
    raise ImportError("no module named argostranslate")


class FakePackageApi:
    """Stands in for argostranslate.package."""

    def __init__(self, available_pairs=(), installed_pairs=()):
        self.available_pairs = list(available_pairs)
        self.installed_pairs = list(installed_pairs)
        self.installed = []

    def get_installed_packages(self):
        return [_FakePackage(*pair) for pair in self.installed_pairs]

    def get_available_packages(self):
        return [_FakePackage(*pair) for pair in self.available_pairs]

    def update_package_index(self):
        pass

    def install_from_path(self, path):
        self.installed.append(path)


class _FakePackage:
    def __init__(self, from_code, to_code):
        self.from_code = from_code
        self.to_code = to_code

    def download(self):
        return f"/tmp/{self.from_code}-{self.to_code}.argosmodel"


class FakeTranslateApi:
    def __init__(self):
        self.calls = []

    def translate(self, text, source, target):
        self.calls.append((text, source, target))
        return f"translated({source}->{target})"


class TestArgosPackageHandling:
    def install_fakes(self, monkeypatch, package_api):
        from soundvibes import translation

        translate_api = FakeTranslateApi()
        monkeypatch.setattr(translation, "_import_argos", lambda: (package_api, translate_api))
        return translate_api

    def test_a_missing_direct_package_still_translates(self, monkeypatch):
        """Argos routes de->ru through English. Refusing here broke real pairs."""
        from soundvibes.translation import ArgosTranslator

        package_api = FakePackageApi(
            available_pairs=[("en", "ru")], installed_pairs=[("en", "ru"), ("de", "en")]
        )
        translate_api = self.install_fakes(monkeypatch, package_api)

        result = ArgosTranslator().translate("Guten Tag", "de", "ru")

        assert result == "translated(de->ru)"
        assert translate_api.calls == [("Guten Tag", "de", "ru")]

    def test_an_available_direct_package_is_installed_first(self, monkeypatch):
        from soundvibes.translation import ArgosTranslator

        package_api = FakePackageApi(available_pairs=[("de", "ru")])
        self.install_fakes(monkeypatch, package_api)

        ArgosTranslator().translate("Guten Tag", "de", "ru")

        assert package_api.installed == ["/tmp/de-ru.argosmodel"]

    def test_an_already_installed_package_is_not_reinstalled(self, monkeypatch):
        from soundvibes.translation import ArgosTranslator

        package_api = FakePackageApi(available_pairs=[("de", "ru")], installed_pairs=[("de", "ru")])
        self.install_fakes(monkeypatch, package_api)

        ArgosTranslator().translate("Guten Tag", "de", "ru")

        assert package_api.installed == []

    def test_a_failing_translation_is_reported_as_a_translation_error(self, monkeypatch):
        from soundvibes import translation
        from soundvibes.translation import ArgosTranslator, TranslationError

        class Exploding:
            def translate(self, text, source, target):
                raise RuntimeError("model missing")

        monkeypatch.setattr(translation, "_import_argos", lambda: (FakePackageApi(), Exploding()))

        with pytest.raises(TranslationError, match="de->ru"):
            ArgosTranslator().translate("Guten Tag", "de", "ru")
