"""Giorni e scadenze: date ISO, giorno della settimana, festività e differenze fra date."""

import re
from datetime import date, timedelta

from lab_server.holidays import MAX_YEAR, MIN_YEAR, check_year, holiday_date, holiday_name

WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
NOTE = "Indicativo, non normativo."
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_iso(text: str) -> date:
    value = text.strip()
    if not ISO_DATE.fullmatch(value):
        raise ValueError(f'Data "{value}" non valida: formato atteso AAAA-MM-GG (es. 2026-12-25).')
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'Data "{value}" inesistente.') from None
    check_year(day.year)
    return day


def _short(day: date) -> str:
    return f"{day.isoformat()}, {WEEKDAYS[day.weekday()]}"


def describe(day: date, today: date) -> str:
    name = holiday_name(day)
    when = "passata" if day < today else "oggi" if day == today else "futura"
    return f"{_short(day)}{f' ({name})' if name else ''} — {when}."


def date_info(day: str, today: date) -> str:
    return f"{describe(parse_iso(day), today)} {NOTE}"


def find_holiday(name: str, year: int | None, today: date) -> str:
    if year is not None:
        canonical, day = holiday_date(name, year)
        passed = " È già passata." if day < today else ""
        return f"{canonical} {year}: {describe(day, today)}{passed} {NOTE}"
    canonical, day = holiday_date(name, today.year)
    if day >= today:
        return f"{canonical} {today.year}: {describe(day, today)} {NOTE}"
    # Già passata quest'anno: lo si dice esplicitamente, poi si indica la prossima
    _, following = holiday_date(name, today.year + 1)
    return (f"{canonical} {today.year} ({_short(day)}) è già passata; "
            f"la prossima è il {_short(following)}. {NOTE}")


def add_days(days: int, start: str | None, today: date) -> str:
    origin = parse_iso(start) if start else today
    try:
        result = origin + timedelta(days=days)
        check_year(result.year)
    except (OverflowError, ValueError):
        raise ValueError(f"La data risultante è fuori dall'intervallo ammesso ({MIN_YEAR}-{MAX_YEAR}).") from None
    return f"{origin.isoformat()} + {days} giorni = {describe(result, today)} {NOTE}"


def days_between(end: str, start: str | None, today: date) -> str:
    origin = parse_iso(start) if start else today
    target = parse_iso(end)
    return f"Dal {origin.isoformat()} al {target.isoformat()}: {(target - origin).days} giorni. " \
           f"{describe(target, today)} {NOTE}"
