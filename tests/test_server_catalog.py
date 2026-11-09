"""Forma del file dei dati del catalogo dei linguaggi di programmazione."""

import json
from importlib.resources import files

CODES = {
    "C", "CPP", "CS", "COBOL", "FORTRAN", "GO", "HS", "JAVA", "JS", "KT",
    "LISP", "PASCAL", "PHP", "PROLOG", "PY", "RB", "RS", "SQL", "SWIFT", "TS",
}
KEYS = {"code", "name", "year", "authors", "paradigms", "typing", "description"}
PARADIGMS = {"imperativo", "procedurale", "a oggetti", "funzionale", "logico", "dichiarativo", "concorrente"}


def _load() -> list[dict]:
    return json.loads(files("lab_server").joinpath("catalog.json").read_text(encoding="utf-8"))


def test_catalog_file_shape():
    data = _load()
    assert len(data) == 20
    assert {e["code"] for e in data} == CODES
    for e in data:
        assert set(e) == KEYS
        assert e["code"] == e["code"].upper()
        assert isinstance(e["name"], str) and e["name"].strip()
        assert isinstance(e["description"], str) and e["description"].strip()
        assert type(e["year"]) is int and 1950 <= e["year"] <= 2020
        assert isinstance(e["authors"], list) and e["authors"]
        assert all(isinstance(a, str) and a.strip() for a in e["authors"])
        assert isinstance(e["paradigms"], list) and e["paradigms"]
        assert set(e["paradigms"]) <= PARADIGMS
        assert e["typing"] in {"statica", "dinamica"}
