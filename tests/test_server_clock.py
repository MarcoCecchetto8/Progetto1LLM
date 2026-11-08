from datetime import UTC, datetime

import pytest

from lab_server.clock import current_time

FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)  # dopo il cambio dell'ora legale


def test_default_timezone():
    assert current_time(None, "Europe/Rome", FIXED) == "Europe/Rome: 2026-10-26T14:32:05+01:00"


def test_explicit_timezone():
    assert current_time("Asia/Tokyo", "Europe/Rome", FIXED) == "Asia/Tokyo: 2026-10-26T22:32:05+09:00"


def test_summer_time():
    summer = lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    assert current_time(None, "Europe/Rome", summer) == "Europe/Rome: 2026-07-01T12:00:00+02:00"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_blank_uses_default(value):
    assert current_time(value, "Europe/Rome", FIXED).startswith("Europe/Rome: ")


def test_strips_spaces():
    assert current_time(" Asia/Tokyo ", "Europe/Rome", FIXED).startswith("Asia/Tokyo: ")


@pytest.mark.parametrize("bad", ["Marte/Base", "../etc/passwd", "Europe/", "x" * 300, "Europe/Rome.",
    "Europe\\Rome", "Europe/Rome::$DATA", "posixrules"])
def test_unknown_timezone(bad):
    with pytest.raises(ValueError) as error:
        current_time(bad, "Europe/Rome", FIXED)
    assert str(error.value) == f'Fuso orario sconosciuto: "{bad}". Usa un nome IANA, es. Europe/Rome.'
