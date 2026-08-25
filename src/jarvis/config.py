"""Configuration: load, validate, seed on first run.

One human-editable TOML file. Read with the stdlib ``tomllib``, written back (by the
settings UI) with ``tomli_w``, validated with pydantic so a typo produces a sentence
rather than a stack trace.
"""

from __future__ import annotations

import logging
import shutil
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

log = logging.getLogger(__name__)

CONFIG_FILENAME = "jarvis.toml"
PERSONALITY_FILENAME = "personality.txt"


class _Base(BaseModel):
    # Reject unknown keys: a misspelled option that silently does nothing is worse
    # than one that refuses to start.
    model_config = ConfigDict(extra="forbid")


class GeneralConfig(_Base):
    personality_file: str = PERSONALITY_FILENAME
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class AudioConfig(_Base):
    input_device: str = ""
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    frame_ms: Literal[10, 20, 30] = 20


class ClapConfig(_Base):
    enabled: bool = True
    threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    min_gap_ms: int = Field(default=120, ge=10)
    max_gap_ms: int = Field(default=700, ge=50)
    refractory_ms: int = Field(default=1500, ge=0)
    highpass_hz: int = Field(default=2000, ge=100)

    @field_validator("max_gap_ms")
    @classmethod
    def _gap_order(cls, v: int, info) -> int:
        lo = info.data.get("min_gap_ms")
        if lo is not None and v <= lo:
            raise ValueError(f"max_gap_ms ({v}) must exceed min_gap_ms ({lo})")
        return v


class SttConfig(_Base):
    backend: Literal["faster_whisper", "cloud"] = "faster_whisper"
    model: str = "small.en"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    compute_type: Literal["auto", "int8", "float16", "float32"] = "auto"
    language: str = "en"
    max_utterance_s: float = Field(default=30.0, gt=0)


class CancelConfig(_Base):
    enabled: bool = True
    phrases: list[str] = Field(default_factory=lambda: ["cancel", "stop jarvis"])
    model: str = "tiny.en"

    @field_validator("phrases")
    @classmethod
    def _normalise(cls, v: list[str]) -> list[str]:
        cleaned = [p.strip().lower() for p in v if p.strip()]
        if not cleaned:
            raise ValueError("cancel.phrases cannot be empty when cancel is enabled")
        return cleaned


class LlmConfig(_Base):
    model: str = "claude-opus-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = Field(default=4096, ge=256)
    history_turns: int = Field(default=12, ge=0)
    fast_mode: bool = False
    refusal_fallbacks: bool = True


class ElevenLabsConfig(_Base):
    voice_id: str = ""
    model_id: str = "eleven_turbo_v2_5"


class PiperConfig(_Base):
    model_path: str = ""


class TtsConfig(_Base):
    backend: Literal["system", "elevenlabs", "piper"] = "system"
    voice: str = ""
    rate: int = Field(default=190, ge=60, le=400)
    elevenlabs: ElevenLabsConfig = Field(default_factory=ElevenLabsConfig)
    piper: PiperConfig = Field(default_factory=PiperConfig)


class StartupConfig(_Base):
    enabled: bool = False
    order: Literal["prompt_first", "open_first"] = "prompt_first"
    prompt: str = ""
    open: list[str] = Field(default_factory=list)


class ActionsConfig(_Base):
    allow_automation: bool = False
    automation_allowlist: list[str] = Field(default_factory=list)
    search_engine: str = "https://duckduckgo.com/?q={query}"

    @field_validator("search_engine")
    @classmethod
    def _has_placeholder(cls, v: str) -> str:
        if "{query}" not in v:
            raise ValueError("actions.search_engine must contain a {query} placeholder")
        return v


class Config(_Base):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    clap: ClapConfig = Field(default_factory=ClapConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    cancel: CancelConfig = Field(default_factory=CancelConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    startup: StartupConfig = Field(default_factory=StartupConfig)
    actions: ActionsConfig = Field(default_factory=ActionsConfig)

    # Populated by load(); not read from the file.
    source_path: Path | None = Field(default=None, exclude=True)

    @property
    def personality_path(self) -> Path:
        """Resolve personality_file relative to the config file's own directory."""
        p = Path(self.general.personality_file).expanduser()
        if p.is_absolute() or self.source_path is None:
            return p
        return (self.source_path.parent / p).resolve()

    def read_personality(self) -> str:
        path = self.personality_path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            log.warning("could not read personality file %s: %s", path, exc)
            return "You are Jarvis, a concise and unflappable British assistant."


class ConfigError(Exception):
    """Config file is missing, malformed, or invalid. The message is user-facing."""


def _bundled_defaults_dir() -> Path:
    """The config/ directory shipped with the source tree or inside the bundle."""
    # src/jarvis/config.py -> src/jarvis -> src -> <root>/config
    candidate = Path(__file__).resolve().parents[2] / "config"
    if candidate.is_dir():
        return candidate
    # py2app puts data files in Contents/Resources, alongside the package.
    return Path(__file__).resolve().parent / "config"


def ensure_user_config(config_dir: Path) -> Path:
    """Create the user config directory and seed it on first run.

    Returns the path to the config file. Idempotent; never overwrites.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / CONFIG_FILENAME
    defaults = _bundled_defaults_dir()

    if not target.exists():
        source = defaults / "jarvis.example.toml"
        if source.exists():
            shutil.copyfile(source, target)
            log.info("seeded config at %s", target)
        else:
            target.write_text("# Jarvis config\n", encoding="utf-8")
            log.warning("no bundled example config found at %s", source)

    personality = config_dir / PERSONALITY_FILENAME
    if not personality.exists():
        source = defaults / PERSONALITY_FILENAME
        if source.exists():
            shutil.copyfile(source, personality)

    return target


def load(path: Path) -> Config:
    """Read and validate the config file.

    Raises ConfigError with a message fit to show the user.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name} is not valid TOML: {exc}") from exc

    try:
        cfg = Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc

    cfg.source_path = path
    return cfg


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"{path.name} has {exc.error_count()} problem(s):"]
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"  {where}: {err['msg']}")
    return "\n".join(lines)


def load_or_seed(config_dir: Path) -> Config:
    """The normal entry point: seed if absent, then load."""
    return load(ensure_user_config(config_dir))
