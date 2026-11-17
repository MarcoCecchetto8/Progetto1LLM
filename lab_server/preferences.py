"""Preferenze dell'utente: valori ammessi e validazione, condivise da server e host."""

import json
from dataclasses import dataclass

from lab_server.timezones import get_timezone

PREFERENCES_URI = "utente://preferenze"
LANGUAGES = ("italiano", "inglese", "spagnolo")
STYLES = ("sintetico", "dettagliato")

DEFAULT_LANGUAGE = "italiano"
DEFAULT_STYLE = "sintetico"


@dataclass(frozen=True)
class Preferences:
    lingua: str
    fuso_orario: str
    stile: str


def _allowed(field: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    if field == "lingua":
        return value in LANGUAGES
    if field == "stile":
        return value in STYLES
    return get_timezone(value) is not None


def parse_preferences(
    text: str | None, fallback_timezone: str, reason: str = ""
) -> tuple[Preferences, list[str]]:
    """Preferenze valide dal testo JSON e avvisi; ogni valore non valido torna alla riserva."""
    defaults = Preferences(DEFAULT_LANGUAGE, fallback_timezone, DEFAULT_STYLE)
    fallback_text = f"uso {DEFAULT_LANGUAGE}, {DEFAULT_STYLE}, {fallback_timezone}"
    if text is None:
        return defaults, [f"resource non disponibile ({reason}): {fallback_text}"]
    try:
        data = json.loads(text)
    except ValueError:
        return defaults, [f"contenuto non valido (JSON non leggibile): {fallback_text}"]
    if not isinstance(data, dict):
        return defaults, [f"contenuto non valido (non è un oggetto JSON): {fallback_text}"]

    warnings: list[str] = []
    values: dict[str, str] = {}
    for field, fallback in vars(defaults).items():
        if field not in data:
            warnings.append(f"{field} mancante: uso '{fallback}'")
            values[field] = fallback
        elif _allowed(field, data[field]):
            values[field] = data[field]
        else:
            warnings.append(f"{field} '{data[field]}' non ammesso: uso '{fallback}'")
            values[field] = fallback
    return Preferences(**values), warnings
