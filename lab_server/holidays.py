"""Festività nazionali italiane: a data fissa dal file locale, Pasqua calcolata."""

import json
import unicodedata
from datetime import date, timedelta
from functools import cache
from importlib.resources import files

MIN_YEAR = 1900
MAX_YEAR = 2200


def easter(year: int) -> date:
    """Pasqua nel calendario gregoriano (algoritmo anonimo di Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _key(name: str) -> str:
    # Senza accenti, maiuscole e spazi doppi: "lunedi dell'angelo" e "Lunedì dell'Angelo" coincidono
    text = unicodedata.normalize("NFKD", name.replace("’", "'"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


@cache
def _holidays() -> dict:
    return json.loads(files("lab_server").joinpath("holidays.json").read_text(encoding="utf-8"))


@cache
def _by_key() -> dict[str, dict]:
    data = _holidays()
    index = {}
    for entry in data["fixed"] + data["easter"]:
        for name in [entry["name"], *entry["aliases"]]:
            index[_key(name)] = entry
    return index


def check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"Anno {year} fuori dall'intervallo ammesso ({MIN_YEAR}-{MAX_YEAR}).")


def _date_of(entry: dict, year: int) -> date:
    if "offset" in entry:
        return easter(year) + timedelta(days=entry["offset"])
    return date(year, entry["month"], entry["day"])


def holiday_date(name: str, year: int) -> tuple[str, date]:
    """Nome ufficiale e data della festività nell'anno; ValueError se sconosciuta o anno fuori intervallo."""
    check_year(year)
    entry = _by_key().get(_key(name))
    if entry is None:
        names = ", ".join(e["name"] for e in _holidays()["fixed"] + _holidays()["easter"])
        raise ValueError(f'Festività "{name.strip()}" sconosciuta. Festività disponibili: {names}.')
    return entry["name"], _date_of(entry, year)


def holiday_name(day: date) -> str | None:
    data = _holidays()
    # Pasqua o Pasquetta possono cadere il 25 aprile: si nominano tutte le festività del giorno
    names = [entry["name"] for entry in data["fixed"] + data["easter"] if _date_of(entry, day.year) == day]
    return " e ".join(names) or None
