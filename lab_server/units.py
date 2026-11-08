"""Convertitore di unità: elenco chiuso di unità metriche per lunghezza, peso, volume e temperatura."""

import math
from decimal import Decimal
from typing import Literal

Unit = Literal["mm", "cm", "dm", "m", "dam", "hm", "km",
               "mg", "cg", "dg", "g", "dag", "hg", "kg", "q", "t",
               "ml", "cl", "dl", "l", "dal", "hl", "m3",
               "C", "K"]

# Fattori rispetto all'unità base di ogni categoria (m, g, l); Decimal evita artefatti come 110000.00000000001
FACTORS = {
    "lunghezza": {"mm": "0.001", "cm": "0.01", "dm": "0.1", "m": "1", "dam": "10", "hm": "100", "km": "1000"},
    "peso": {"mg": "0.001", "cg": "0.01", "dg": "0.1", "g": "1", "dag": "10", "hg": "100", "kg": "1000",
             "q": "100000", "t": "1000000"},
    "volume": {"ml": "0.001", "cl": "0.01", "dl": "0.1", "l": "1", "dal": "10", "hl": "100", "m3": "1000"},
    "temperatura": {"C": "0", "K": "0"},
}
CATEGORY = {unit: category for category, units in FACTORS.items() for unit in units}
ABSOLUTE_ZERO_C = Decimal("-273.15")


def _format(number: Decimal) -> str:
    text = format(number.normalize(), "f")
    return "0" if text == "-0" else text


def convert(value: float, from_unit: str, to_unit: str) -> str:
    """Converte value da from_unit a to_unit; ValueError per unità non ammesse o conversioni impossibili."""
    for unit in (from_unit, to_unit):
        if unit not in CATEGORY:
            raise ValueError(f'Unità "{unit}" non ammessa. Unità ammesse: {", ".join(CATEGORY)}.')
    if not math.isfinite(value):
        raise ValueError(f"Il valore deve essere un numero finito, non {value}.")
    source, target = CATEGORY[from_unit], CATEGORY[to_unit]
    if source != target:
        raise ValueError(f"Conversione impossibile: {from_unit} è un'unità di {source}, {to_unit} di {target}.")
    amount = Decimal(str(value))
    if source == "temperatura":
        celsius = amount if from_unit == "C" else amount + ABSOLUTE_ZERO_C
        if celsius < ABSOLUTE_ZERO_C:
            raise ValueError(f"{_format(amount)} {from_unit} è sotto lo zero assoluto (-273.15 C, 0 K).")
        result = celsius if to_unit == "C" else celsius - ABSOLUTE_ZERO_C
    else:
        if amount < 0:
            raise ValueError(f"Una quantità di {source} non può essere negativa: {_format(amount)} {from_unit}.")
        result = amount * Decimal(FACTORS[source][from_unit]) / Decimal(FACTORS[source][to_unit])
    return f"{_format(amount)} {from_unit} = {_format(result)} {to_unit}"
