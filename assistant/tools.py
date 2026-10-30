"""Strumento orologio con fuso orario esplicito."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from langchain_core.tools import BaseTool, tool

from assistant.timezones import get_timezone

logger = logging.getLogger("assistant.tools")


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_clock_tool(default_timezone: str, now: Callable[[], datetime] = utc_now) -> BaseTool:
    @tool
    def get_current_time(timezone: str | None = None) -> str:
        """Restituisce data e ora attuali in un fuso orario.

        Il parametro timezone è un nome IANA (es. Europe/Rome, Asia/Tokyo).
        Se omesso, si usa il fuso orario predefinito.
        """
        name = (timezone or "").strip() or default_timezone
        zone = get_timezone(name)
        if zone is None:
            result = f'Fuso orario sconosciuto: "{name}". Usa un nome IANA, es. Europe/Rome.'
        else:
            result = f"{name}: {now().astimezone(zone).isoformat(timespec='seconds')}"
        logger.info("[strumento] get_current_time(timezone=%s) → %s", name, result)
        return result

    return get_current_time
