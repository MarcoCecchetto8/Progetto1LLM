from datetime import date

import pytest

from lab_server.holidays import easter, holiday_date, holiday_name


@pytest.mark.parametrize("year,expected", [
    (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2000, date(2000, 4, 23)), (2025, date(2025, 4, 20)),
])
def test_easter(year, expected):
    assert easter(year) == expected


def test_fixed_holiday():
    assert holiday_date("Natale", 2026) == ("Natale", date(2026, 12, 25))


def test_easter_monday():
    assert holiday_date("Lunedì dell'Angelo", 2026) == ("Lunedì dell'Angelo", date(2026, 4, 6))


@pytest.mark.parametrize("name,canonical", [
    ("pasquetta", "Lunedì dell'Angelo"), ("lunedi dell'angelo", "Lunedì dell'Angelo"), ("NATALE", "Natale"),
    (" 25  aprile ", "Festa della Liberazione"), ("Capodanno", "Capodanno"), ("immacolata", "Immacolata Concezione"),
])
def test_names_and_aliases(name, canonical):
    assert holiday_date(name, 2026)[0] == canonical


def test_holiday_name():
    assert holiday_name(date(2026, 4, 6)) == "Lunedì dell'Angelo"
    assert holiday_name(date(2026, 12, 25)) == "Natale"
    assert holiday_name(date(2026, 3, 3)) is None


def test_unknown_holiday_lists_names():
    with pytest.raises(ValueError, match="sconosciuta") as error:
        holiday_date("Halloween", 2026)
    assert "Natale" in str(error.value) and "Pasqua" in str(error.value)


@pytest.mark.parametrize("year", [1899, 2201])
def test_year_out_of_range(year):
    with pytest.raises(ValueError, match="1900"):
        holiday_date("Natale", year)
