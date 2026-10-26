import logging
from datetime import UTC, datetime

import pytest

from assistant.tools import make_clock_tool

FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)  # dopo il cambio dell'ora legale


def test_default_timezone():
    assert make_clock_tool("Europe/Rome", FIXED).invoke({}) == "Europe/Rome: 2026-10-26T14:32:05+01:00"


def test_explicit_timezone():
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": "Asia/Tokyo"}) == "Asia/Tokyo: 2026-10-26T22:32:05+09:00"


def test_summer_time():
    tool = make_clock_tool("Europe/Rome", lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    assert tool.invoke({}) == "Europe/Rome: 2026-07-01T12:00:00+02:00"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_blank_uses_default(value):
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": value}).startswith("Europe/Rome: ")


def test_strips_spaces():
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": " Asia/Tokyo "}).startswith("Asia/Tokyo: ")


@pytest.mark.parametrize("bad", ["Marte/Base", "../etc/passwd", "Europe/"])
def test_unknown_timezone(bad):
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": bad}) == \
        f'Fuso orario sconosciuto: "{bad}". Usa un nome IANA, es. Europe/Rome.'


def test_logs_call(caplog):
    caplog.set_level(logging.INFO, "assistant.tools")
    make_clock_tool("Europe/Rome", FIXED).invoke({})
    assert "[strumento] get_current_time(timezone=Europe/Rome) → Europe/Rome: 2026-10-26T14:32:05+01:00" in caplog.text
