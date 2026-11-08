from datetime import date

import pytest

from lab_server.dates import add_days, date_info, days_between, find_holiday, parse_iso

TODAY = date(2026, 11, 2)
NOTE = "Indicativo, non normativo."


def test_date_info_future_holiday():
    text = date_info("2026-12-25", TODAY)
    assert "2026-12-25, venerdì (Natale) — futura." in text and text.endswith(NOTE)


def test_date_info_past_and_today():
    assert "passata" in date_info("2026-01-01", TODAY)
    assert "— oggi." in date_info("2026-11-02", TODAY)


def test_date_info_leap_day():
    assert "2028-02-29, martedì" in date_info("2028-02-29", TODAY)


def test_find_holiday_already_passed_this_year():
    text = find_holiday("Pasqua", None, TODAY)
    assert "Pasqua 2026 (2026-04-05, domenica) è già passata; la prossima è il 2027-03-28, domenica" in text
    assert text.endswith(NOTE)


def test_find_holiday_still_to_come():
    text = find_holiday("Natale", None, TODAY)
    assert "2026-12-25, venerdì" in text and "già passat" not in text


def test_find_holiday_explicit_past_year():
    text = find_holiday("Pasqua", 2025, TODAY)
    assert "2025-04-20" in text and "già passata" in text


def test_find_holiday_today_is_not_passed():
    text = find_holiday("Ognissanti", None, date(2026, 11, 1))
    assert "2026-11-01" in text and "già passat" not in text


def test_add_days_from_today():
    assert "2026-11-26, giovedì" in add_days(24, None, TODAY)


def test_add_days_across_year():
    assert "2027-01-13" in add_days(24, "2026-12-20", TODAY)


def test_add_days_into_past():
    assert "passata" in add_days(-2, None, TODAY)


def test_days_between_until_christmas():
    text = days_between("2026-12-25", None, TODAY)
    assert "Dal 2026-11-02 al 2026-12-25: 53 giorni." in text and text.endswith(NOTE)


def test_days_between_past_date():
    text = days_between("2026-11-01", None, TODAY)
    assert "-1 giorni" in text and "passata" in text


def test_parse_iso_strips_spaces():
    assert parse_iso(" 2026-12-25 ") == date(2026, 12, 25)


@pytest.mark.parametrize("text", ["25/12/2026", "2026-12-25T10:00", "2026-1-5", "domani", ""])
def test_parse_iso_rejects_other_formats(text):
    with pytest.raises(ValueError, match="AAAA-MM-GG"):
        parse_iso(text)


def test_parse_iso_rejects_missing_day():
    with pytest.raises(ValueError, match="inesistente"):
        parse_iso("2026-02-30")


@pytest.mark.parametrize("days,start", [(100000, None), (-100000, None), (10, "2200-12-30")])
def test_add_days_out_of_range(days, start):
    with pytest.raises(ValueError, match="1900"):
        add_days(days, start, TODAY)


def test_date_info_year_out_of_range():
    with pytest.raises(ValueError, match="1900"):
        date_info("1800-01-01", TODAY)
