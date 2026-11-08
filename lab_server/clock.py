"""Orologio con fuso orario esplicito."""

from collections.abc import Callable
from datetime import UTC, datetime

from lab_server.timezones import get_timezone


def utc_now() -> datetime:
    return datetime.now(UTC)


def current_time(timezone: str | None, default_timezone: str, now: Callable[[], datetime] = utc_now) -> str:
    """Data e ora attuali nel fuso indicato (o in quello predefinito); ValueError se il fuso è sconosciuto."""
    name = (timezone or "").strip() or default_timezone
    zone = get_timezone(name)
    if zone is None:
        raise ValueError(f'Fuso orario sconosciuto: "{name}". Usa un nome IANA, es. Europe/Rome.')
    return f"{name}: {now().astimezone(zone).isoformat(timespec='seconds')}"
