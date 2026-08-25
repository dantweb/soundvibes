"""Which language packages an offline install actually needs."""
import pytest

from soundvibes.offline import required_pairs, resolve_packages


class TestRequiredPairs:
    def test_every_spoken_language_to_every_target(self):
        assert required_pairs(["en", "de"], ["fr"]) == [("en", "fr"), ("de", "fr")]

    def test_a_target_that_is_also_spoken_is_not_paired_with_itself(self):
        assert ("de", "de") not in required_pairs(["en", "de"], ["de"])

    def test_no_targets_falls_back_to_translating_between_spoken_languages(self):
        """Historic behaviour: with no targets, prepare the spoken pairs."""
        pairs = required_pairs(["en", "de"], [])
        assert sorted(pairs) == [("de", "en"), ("en", "de")]

    def test_targets_are_included_even_when_never_spoken(self):
        """The gap this fixes: 'fr' was ignored because it was not a spoken language."""
        pairs = required_pairs(["en", "de", "ru"], ["fr"])
        assert ("en", "fr") in pairs
        assert ("de", "fr") in pairs
        assert ("ru", "fr") in pairs

    def test_duplicates_are_removed(self):
        assert required_pairs(["en", "en"], ["fr"]) == [("en", "fr")]


class TestResolvePackages:
    def test_a_direct_package_is_chosen_when_available(self):
        to_install, unreachable = resolve_packages(
            available=[("de", "fr")], sources=["de"], targets=["fr"])

        assert to_install == [("de", "fr")]
        assert unreachable == []

    def test_pivot_legs_are_chosen_when_there_is_no_direct_package(self):
        """Argos routes through English, so install the two legs instead."""
        to_install, unreachable = resolve_packages(
            available=[("de", "en"), ("en", "fr")], sources=["de"], targets=["fr"])

        assert to_install == [("de", "en"), ("en", "fr")]
        assert unreachable == []

    def test_a_pair_with_neither_route_is_reported_unreachable(self):
        to_install, unreachable = resolve_packages(
            available=[("de", "en")], sources=["de"], targets=["fr"])

        assert to_install == []
        assert unreachable == [("de", "fr")]

    def test_shared_pivot_legs_are_installed_once(self):
        to_install, _ = resolve_packages(
            available=[("de", "en"), ("ru", "en"), ("en", "fr")],
            sources=["de", "ru"], targets=["fr"])

        assert to_install.count(("en", "fr")) == 1

    def test_a_pair_needing_no_pivot_leg_from_english_is_direct(self):
        to_install, unreachable = resolve_packages(
            available=[("en", "fr")], sources=["en"], targets=["fr"])

        assert to_install == [("en", "fr")]

    def test_the_pivot_language_is_configurable(self):
        to_install, unreachable = resolve_packages(
            available=[("de", "es"), ("es", "fr")], sources=["de"], targets=["fr"],
            pivot="es")

        assert to_install == [("de", "es"), ("es", "fr")]

    def test_nothing_needed_when_source_equals_target(self):
        to_install, unreachable = resolve_packages(
            available=[], sources=["fr"], targets=["fr"])

        assert to_install == [] and unreachable == []
