from __future__ import annotations

from pathlib import Path

import pytest

from jarvis import config as cfgmod


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "jarvis.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    cfg = cfgmod.load(write(tmp_path, ""))
    assert cfg.llm.model == "claude-opus-5"
    assert cfg.llm.effort == "low"
    assert cfg.llm.refusal_fallbacks is True
    assert cfg.llm.fast_mode is False
    assert cfg.tts.backend == "system"
    assert cfg.clap.enabled is True


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "[llm]\nmodl = 'claude-opus-5'\n")
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load(path)
    assert "modl" in str(exc.value)


def test_malformed_toml_names_the_file(tmp_path: Path) -> None:
    path = write(tmp_path, "[llm\n")
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load(path)
    assert "jarvis.toml" in str(exc.value)


def test_clap_gap_ordering_is_enforced(tmp_path: Path) -> None:
    path = write(tmp_path, "[clap]\nmin_gap_ms = 500\nmax_gap_ms = 200\n")
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load(path)
    assert "max_gap_ms" in str(exc.value)


def test_search_engine_needs_a_placeholder(tmp_path: Path) -> None:
    path = write(tmp_path, "[actions]\nsearch_engine = 'https://example.com/'\n")
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(path)


def test_cancel_phrases_are_lowercased_and_stripped(tmp_path: Path) -> None:
    cfg = cfgmod.load(write(tmp_path, "[cancel]\nphrases = ['  Stop Jarvis ', 'HALT']\n"))
    assert cfg.cancel.phrases == ["stop jarvis", "halt"]


def test_cancel_phrases_cannot_be_empty(tmp_path: Path) -> None:
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(write(tmp_path, "[cancel]\nphrases = ['  ']\n"))


def test_effort_is_constrained(tmp_path: Path) -> None:
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(write(tmp_path, "[llm]\neffort = 'turbo'\n"))


def test_frame_ms_must_suit_webrtcvad(tmp_path: Path) -> None:
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(write(tmp_path, "[audio]\nframe_ms = 25\n"))
    assert cfgmod.load(write(tmp_path, "[audio]\nframe_ms = 30\n")).audio.frame_ms == 30


def test_personality_resolves_relative_to_the_config_file(tmp_path: Path) -> None:
    (tmp_path / "voice.txt").write_text("Be terse.", encoding="utf-8")
    cfg = cfgmod.load(write(tmp_path, "[general]\npersonality_file = 'voice.txt'\n"))
    assert cfg.personality_path == (tmp_path / "voice.txt").resolve()
    assert cfg.read_personality() == "Be terse."


def test_missing_personality_falls_back_rather_than_crashing(tmp_path: Path) -> None:
    cfg = cfgmod.load(write(tmp_path, "[general]\npersonality_file = 'absent.txt'\n"))
    assert "Jarvis" in cfg.read_personality()


def test_seeding_is_idempotent(tmp_path: Path) -> None:
    target = cfgmod.ensure_user_config(tmp_path / "Jarvis")
    assert target.exists()
    target.write_text("[llm]\nmax_tokens = 999\n", encoding="utf-8")
    again = cfgmod.ensure_user_config(tmp_path / "Jarvis")
    assert again == target
    assert cfgmod.load(again).llm.max_tokens == 999  # not clobbered


def test_the_shipped_example_config_is_valid() -> None:
    example = Path(__file__).resolve().parents[1] / "config" / "jarvis.example.toml"
    cfg = cfgmod.load(example)
    assert cfg.llm.model
    assert cfg.cancel.phrases
