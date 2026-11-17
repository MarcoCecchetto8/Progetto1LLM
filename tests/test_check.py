import asyncio

import pytest

from lab_server.check import check, parse_args


def test_parse_args_reads_json_values():
    assert parse_args(["timezone=Asia/Tokyo", "value=2.5"]) == {"timezone": "Asia/Tokyo", "value": 2.5}


def test_parse_args_keeps_text_with_spaces_and_equals():
    assert parse_args(["expression=10 * 7 / 9", "text=a=b"]) == {"expression": "10 * 7 / 9", "text": "a=b"}


def test_parse_args_without_equals():
    with pytest.raises(SystemExit):
        parse_args(["Asia/Tokyo"])


def test_check_lists_resource(capfd):
    assert asyncio.run(check([])) == 0
    lines = capfd.readouterr().out.splitlines()
    assert any(line.startswith("resource utente://preferenze: preferenze (application/json)") for line in lines)
