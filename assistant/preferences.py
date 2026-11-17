"""Lettura delle preferenze dell'utente (resource utente://preferenze) all'avvio."""

import logging
from collections.abc import Callable

from assistant.mcp_client import MCPResourceError
from lab_server.preferences import PREFERENCES_URI, Preferences, parse_preferences

logger = logging.getLogger("assistant")


def load_preferences(read: Callable[[str], str], fallback_timezone: str) -> Preferences:
    # Una resource non disponibile non ferma l'avvio; un collegamento caduto (MCPConnectionError) sì
    try:
        text, reason = read(PREFERENCES_URI), ""
    except MCPResourceError as error:
        text, reason = None, str(error)
    preferences, warnings = parse_preferences(text, fallback_timezone, reason)
    for warning in warnings:
        logger.warning("[preferenze] %s", warning)
    logger.info("[preferenze] utente://preferenze: lingua=%s, fuso_orario=%s, stile=%s",
                preferences.lingua, preferences.fuso_orario, preferences.stile)
    return preferences
