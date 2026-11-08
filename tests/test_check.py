import pytest

from lab_server.check import parse_args


def test_parse_args_reads_json_values():
    assert parse_args(["timezone=Asia/Tokyo", "value=2.5"]) == {"timezone": "Asia/Tokyo", "value": 2.5}


def test_parse_args_keeps_text_with_spaces_and_equals():
    assert parse_args(["expression=10 * 7 / 9", "text=a=b"]) == {"expression": "10 * 7 / 9", "text": "a=b"}


def test_parse_args_without_equals():
    with pytest.raises(SystemExit):
        parse_args(["Asia/Tokyo"])
