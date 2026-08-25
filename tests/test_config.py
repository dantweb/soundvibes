"""config.yaml is the single source of every tunable value."""
import pytest

from soundvibes.config import CONFIG, ConfigError, Section, load_config


class TestLoading:
    def test_the_shipped_config_loads(self):
        assert CONFIG.audio.sample_rate == 16000

    def test_nested_sections_are_dot_accessible(self):
        assert CONFIG.translation.claude.model.startswith("claude-")

    def test_lists_come_back_as_lists(self):
        # Which languages are configured is the user's business; that the loader
        # returns a usable list is ours.
        assert isinstance(CONFIG.transcription.languages, list)
        assert CONFIG.transcription.languages
        assert len(CONFIG.devices.loopback_hints) > 5

    def test_a_missing_key_names_its_full_path(self):
        with pytest.raises(ConfigError, match="audio.nonexistent"):
            _ = CONFIG.audio.nonexistent

    def test_get_returns_a_default_instead_of_raising(self):
        assert CONFIG.audio.get("nonexistent", "fallback") == "fallback"

    def test_membership_can_be_tested(self):
        assert "sample_rate" in CONFIG.audio
        assert "nonexistent" not in CONFIG.audio


class TestCustomFiles:
    def test_an_alternative_file_can_be_loaded(self, tmp_path):
        path = tmp_path / "custom.yaml"
        path.write_text("audio:\n  sample_rate: 8000\n")

        assert load_config(path).audio.sample_rate == 8000

    def test_malformed_yaml_is_reported_clearly(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("audio:\n  - this is a list\n   bad indent:\n")

        with pytest.raises(ConfigError, match="not valid YAML"):
            load_config(path)

    def test_a_non_mapping_document_is_rejected(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- one\n- two\n")

        with pytest.raises(ConfigError, match="mapping"):
            load_config(path)

    def test_a_missing_file_is_reported(self, tmp_path):
        with pytest.raises(Exception):
            load_config(tmp_path / "absent.yaml")


class TestEveryTunableIsPresent:
    """If a section disappears from config.yaml, the package cannot import."""

    @pytest.mark.parametrize("section", [
        "audio", "sources", "endpointer", "transcription", "translation",
        "output", "pipeline", "devices",
    ])
    def test_section_exists(self, section):
        assert isinstance(getattr(CONFIG, section), Section)

    @pytest.mark.parametrize("path", [
        ("audio", "sample_rate"), ("audio", "frame_ms"), ("audio", "block_poll_seconds"),
        ("endpointer", "sensitivity"), ("endpointer", "onset_frames"),
        ("transcription", "hallucinations"), ("transcription", "beam_size"),
        ("translation", "cache_entries"), ("translation", "file_prefix"),
        ("pipeline", "poll_seconds"), ("output", "format"),
    ])
    def test_key_exists(self, path):
        section, key = path
        assert getattr(getattr(CONFIG, section), key) is not None


class TestValuesReachTheCode:
    def test_constants_are_derived_from_the_file(self):
        from soundvibes.constants import FRAME_SAMPLES, SAMPLE_RATE

        assert SAMPLE_RATE == CONFIG.audio.sample_rate
        assert FRAME_SAMPLES == SAMPLE_RATE * CONFIG.audio.frame_ms // 1000

    def test_endpointer_defaults_are_derived_from_the_file(self):
        from soundvibes.endpointing import SpeechEndpointer

        assert SpeechEndpointer.ONSET_FRAMES == CONFIG.endpointer.onset_frames

    def test_hallucination_list_is_derived_from_the_file(self):
        from soundvibes.transcription import DEFAULT_HALLUCINATIONS

        assert len(DEFAULT_HALLUCINATIONS) == len(CONFIG.transcription.hallucinations)

    def test_loopback_hints_are_derived_from_the_file(self):
        from soundvibes.devices import LOOPBACK_HINTS

        assert list(LOOPBACK_HINTS) == list(CONFIG.devices.loopback_hints)
