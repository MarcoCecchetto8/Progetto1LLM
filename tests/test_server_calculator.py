import time

import pytest

from lab_server.calculator import calculate


@pytest.mark.parametrize("expression,expected", [
    ("10 * 7 / 9", "10 * 7 / 9 = 7.777777777777778"),
    ("2^5", "2^5 = 32"),
    ("2**5", "2**5 = 32"),
    ("-3 + 5", "-3 + 5 = 2"),
    ("(2 + 3) * 4", "(2 + 3) * 4 = 20"),
    ("8 / 2", "8 / 2 = 4"),
    ("2.5 * 2", "2.5 * 2 = 5"),
    ("+4 - -2", "+4 - -2 = 6"),
    ("  1 + 1  ", "1 + 1 = 2"),
])
def test_allowed_expressions(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression,char", [
    ("x + 1", "x"), ("sqrt(4)", "s"), ("__import__('os')", "_"),
    ("3 × 4", "×"), ("8 ÷ 2", "÷"), ("2,5 * 2", ","),
])
def test_disallowed_characters(expression, char):
    with pytest.raises(ValueError, match="non ammesso") as error:
        calculate(expression)
    assert f'"{char}"' in str(error.value)


def test_equation_rejected():
    with pytest.raises(ValueError, match="equazion"):
        calculate("2x = 28")


def test_division_by_zero():
    with pytest.raises(ValueError, match="zero"):
        calculate("1/0")


@pytest.mark.parametrize("expression", ["3 +* 4", "(2 + 3", "2 3", "()"])
def test_malformed(expression):
    with pytest.raises(ValueError, match="non valida"):
        calculate(expression)


@pytest.mark.parametrize("expression", ["", "   "])
def test_empty(expression):
    with pytest.raises(ValueError, match="vuota"):
        calculate(expression)


@pytest.mark.parametrize("expression", ["9^9^9", "10^101", "2^1001", "(10^99) * (10^99)"])
def test_too_large_is_fast(expression):
    start = time.perf_counter()
    with pytest.raises(ValueError, match="troppo grand"):
        calculate(expression)
    assert time.perf_counter() - start < 1


def test_too_long():
    with pytest.raises(ValueError, match="lung"):
        calculate("1" * 201)


def test_complex_result_rejected():
    with pytest.raises(ValueError, match="reale"):
        calculate("(-8)^0.5")


def test_huge_literal_rejected():
    with pytest.raises(ValueError, match="troppo grand"):
        calculate("1" * 150)


@pytest.mark.parametrize("expression,expected", [
    ("10^100/3", "10^100/3 = 3.3333333333333335e+99"),
    ("10^20/1", "10^20/1 = 1e+20"),
    ("2^52 / 1", "2^52 / 1 = 4503599627370496"),
])
def test_large_float_results_keep_only_real_digits(expression, expected):
    assert calculate(expression) == expected
