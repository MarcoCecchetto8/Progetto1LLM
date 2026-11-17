import logging

import pytest

from assistant.mcp_client import MCPConnectionError, MCPResourceError
from assistant.preferences import load_preferences
from lab_server.preferences import Preferences

VALID = '{"lingua": "inglese", "fuso_orario": "America/New_York", "stile": "dettagliato"}'
INFO = "[preferenze] utente://preferenze: lingua=%s, fuso_orario=%s, stile=%s"


def records(caplog, level):
    return [r.getMessage() for r in caplog.records if r.name == "assistant" and r.levelno == level]


def test_valido_una_riga_info_nessun_warning(caplog):
    caplog.set_level(logging.DEBUG, logger="assistant")
    result = load_preferences(lambda uri: VALID, "Europe/Rome")
    assert result == Preferences("inglese", "America/New_York", "dettagliato")
    assert records(caplog, logging.INFO) == [INFO % ("inglese", "America/New_York", "dettagliato")]
    assert records(caplog, logging.WARNING) == []


def test_resource_non_disponibile_usa_riserve(caplog):
    caplog.set_level(logging.DEBUG, logger="assistant")

    def read(uri):
        assert uri == "utente://preferenze"
        raise MCPResourceError("file delle preferenze non leggibile: x")

    result = load_preferences(read, "Europe/Rome")
    assert result == Preferences("italiano", "Europe/Rome", "sintetico")
    assert records(caplog, logging.WARNING) == [
        "[preferenze] resource non disponibile (file delle preferenze non leggibile: x): "
        "uso italiano, sintetico, Europe/Rome"]
    assert records(caplog, logging.INFO) == [INFO % ("italiano", "Europe/Rome", "sintetico")]


def test_stile_non_ammesso(caplog):
    caplog.set_level(logging.DEBUG, logger="assistant")
    text = '{"lingua": "inglese", "fuso_orario": "America/New_York", "stile": "medio"}'
    result = load_preferences(lambda uri: text, "Europe/Rome")
    assert result.stile == "sintetico"
    warnings = records(caplog, logging.WARNING)
    assert warnings == ["[preferenze] stile 'medio' non ammesso: uso 'sintetico'"]
    assert records(caplog, logging.INFO) == [INFO % ("inglese", "America/New_York", "sintetico")]


def test_connessione_persa_passa():
    def read(uri):
        raise MCPConnectionError("giù")

    with pytest.raises(MCPConnectionError):
        load_preferences(read, "Europe/Rome")
