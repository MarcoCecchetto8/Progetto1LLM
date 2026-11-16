"""Configurazione dell'assistente, letta solo da variabili d'ambiente."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lab_server.timezones import get_timezone

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class ConfigError(Exception):
    """Variabile mancante o non valida; il messaggio nomina la variabile."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    timeout: float
    temperature: float
    max_steps: int
    default_timezone: str
    log_level: str
    notes_service_url: str = ""
    show_reasoning: bool = True
    scope_file: str = "config/ambito.txt"
    max_reviews: int = 3


def _get(env: Mapping[str, str], name: str, default: str | None = None) -> str:
    value = env.get(name, "").strip()
    if value:
        return value
    if default is None:
        raise ConfigError(f"Variabile {name} mancante: impostala nel file .env.")
    return default


def _number(env: Mapping[str, str], name: str, default: str, cast, minimum, kind: str):
    raw = _get(env, name, default)
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} non valida: '{raw}' non è {kind}.") from None
    if value < minimum:
        raise ConfigError(f"{name} non valida: {raw} (minimo {minimum}).")
    return value


def load_settings(env: Mapping[str, str]) -> Settings:
    base_url = _get(env, "LMSTUDIO_BASE_URL")
    model = _get(env, "LMSTUDIO_MODEL")

    timeout = _number(env, "LMSTUDIO_TIMEOUT", "120", float, 0, "un numero")
    if timeout <= 0:
        raise ConfigError(f"LMSTUDIO_TIMEOUT non valida: {timeout} (deve essere maggiore di 0).")
    temperature = _number(env, "LMSTUDIO_TEMPERATURE", "0.2", float, 0, "un numero")
    max_steps = _number(env, "MAX_STEPS", "5", int, 1, "un intero")

    timezone = _get(env, "DEFAULT_TIMEZONE", "Europe/Rome")
    if get_timezone(timezone) is None:
        raise ConfigError(f"DEFAULT_TIMEZONE non valida: fuso '{timezone}' sconosciuto.")

    log_level = _get(env, "LOG_LEVEL", "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL non valida: '{log_level}' (valori ammessi: {', '.join(LOG_LEVELS)}).")

    notes_url = env.get("NOTES_SERVICE_URL", "").strip().rstrip("/")

    show_reasoning = _get(env, "SHOW_REASONING", "true").lower()
    if show_reasoning not in ("true", "false"):
        raise ConfigError(f"SHOW_REASONING non valida: '{show_reasoning}' (valori ammessi: true, false).")

    scope_file = _get(env, "SCOPE_FILE", "config/ambito.txt")
    max_reviews = _number(env, "MAX_REVIEWS", "3", int, 0, "un intero")

    return Settings(base_url, model, timeout, temperature, max_steps, timezone, log_level, notes_url,
                    show_reasoning == "true", scope_file, max_reviews)


def load_scope(path: str, root: Path) -> str:
    """Legge il testo dell'ambito; il percorso relativo parte dalla radice del progetto."""
    file = Path(path)
    if not file.is_absolute():
        file = root / file
    try:
        text = file.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if not text:
        raise ConfigError(f"SCOPE_FILE non valida: '{path}' non esiste o è vuoto.")
    return text
