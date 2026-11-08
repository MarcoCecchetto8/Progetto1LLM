import pytest

from lab_server.units import convert


@pytest.mark.parametrize("value,source,target,expected", [
    (1.5, "km", "cm", "1.5 km = 150000 cm"),
    (1.1, "km", "cm", "1.1 km = 110000 cm"),
    (3, "hl", "l", "3 hl = 300 l"),
    (2, "q", "kg", "2 q = 200 kg"),
    (1, "t", "q", "1 t = 10 q"),
    (2, "m3", "hl", "2 m3 = 20 hl"),
    (250, "mg", "g", "250 mg = 0.25 g"),
    (5, "km", "km", "5 km = 5 km"),
    (0, "m", "km", "0 m = 0 km"),
])
def test_ratio_conversions(value, source, target, expected):
    assert convert(value, source, target) == expected


@pytest.mark.parametrize("value,source,target,expected", [
    (20, "C", "K", "20 C = 293.15 K"),
    (0, "K", "C", "0 K = -273.15 C"),
    (-10, "C", "K", "-10 C = 263.15 K"),
])
def test_temperature(value, source, target, expected):
    assert convert(value, source, target) == expected


def test_incompatible_categories():
    with pytest.raises(ValueError, match="lunghezza") as error:
        convert(5, "km", "kg")
    assert "peso" in str(error.value)


def test_unknown_unit_lists_allowed():
    with pytest.raises(ValueError, match="non ammessa") as error:
        convert(1, "mi", "km")
    assert "km" in str(error.value) and "hl" in str(error.value)


def test_negative_quantity_rejected():
    with pytest.raises(ValueError, match="negativ"):
        convert(-3, "km", "m")


@pytest.mark.parametrize("value,source", [(-300, "C"), (-1, "K")])
def test_below_absolute_zero(value, source):
    with pytest.raises(ValueError, match="zero assoluto"):
        convert(value, source, "K" if source == "C" else "C")


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_value_rejected(value):
    with pytest.raises(ValueError, match="numero"):
        convert(value, "km", "m")
