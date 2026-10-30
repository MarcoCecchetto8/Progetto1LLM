"""Configurazione dell'assistente, letta solo da variabili d'ambiente."""

from collections.abc import Mapping
from dataclasses import dataclass

from assistant.timezones import get_timezone

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

    return Settings(base_url, model, timeout, temperature, max_steps, timezone, log_level)
