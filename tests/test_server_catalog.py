"""Test del catalogo dei linguaggi: forma dei dati, logica di ricerca e di dettaglio."""

import json
from importlib.resources import files

import pytest

from lab_server.catalog import get_item, search

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


def _results(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- ")]


def test_search_by_name_and_author():
    out = search("Haskell")
    assert "- HS: Haskell (" in out
    assert 'Trovato 1 linguaggio per "Haskell":' in out
    assert "- C: C (" in search("Ritchie")


def test_search_by_paradigm():
    out = search("funzionale", 20)
    assert "HS" in out and "LISP" in out
    assert "- COBOL:" not in out
    assert "- PROLOG:" in search("logico")


def test_search_short_names_and_symbols():
    out = search("C")
    assert _results(out)[0].startswith("- C: C (")
    assert "- COBOL:" not in out and "- PY:" not in out
    assert "- CPP:" in search("c++")
    assert "- CS:" in search("C#")


def test_search_case_insensitive():
    # L'intestazione riporta la query com'è scritta: si confrontano le righe di risultato
    upper = _results(search("FUNZIONALE"))
    assert upper and upper == _results(search("funzionale"))


def test_search_ignores_stop_words_and_punctuation():
    assert _results(search("chi ha creato Haskell?"))[0].startswith("- HS: Haskell (")


def test_search_orders_by_distinct_matches():
    assert _results(search("funzionale Haskell", 20))[0].startswith("- HS:")


def test_search_truncation():
    n = len(_results(search("funzionale", 20)))
    assert n > 2
    out = search("funzionale", 2)
    assert "mostrati 2:" in out
    assert len(_results(out)) == 2
    assert "ripeti la ricerca con max_results più alto" in out
    full = search("funzionale", 20)
    assert "mostrati" not in full and "ripeti la ricerca" not in full


def test_search_no_match():
    assert search("cobra") == (
        'Nessun linguaggio corrisponde a "cobra". Se hai usato parole al plurale riprova al singolare '
        "(es. funzionale); altrimenti il catalogo non lo contiene."
    )


def test_search_plural_suggests_singular():
    out = search("funzionali")
    assert out.startswith("Nessun linguaggio corrisponde a")
    assert "riprova al singolare" in out


@pytest.mark.parametrize("query", ["", "linguaggi di programmazione", "?"])
def test_search_requires_keyword(query):
    with pytest.raises(ValueError, match="parola chiave"):
        search(query)


@pytest.mark.parametrize("n", [0, 21])
def test_search_max_results_out_of_range(n):
    with pytest.raises(ValueError, match="fra 1 e 20"):
        search("python", n)


def test_search_max_results_bounds_valid():
    search("python", 1)
    search("python", 20)


def test_get_item_normalizes_code():
    out = get_item("PY")
    assert get_item("py") == out == get_item(" Py ")
    assert out.startswith("Python (PY)\nAnno: 1991\n")
    assert "Autori: Guido van Rossum" in out
    assert "Tipizzazione: dinamica" in out


def test_get_item_errors():
    with pytest.raises(ValueError) as e:
        get_item("XYZ")
    assert str(e.value) == 'Codice "XYZ" non presente nel catalogo: usa search_catalog per trovare il codice.'
    with pytest.raises(ValueError, match="vuoto"):
        get_item("  ")


@pytest.mark.parametrize("code", ["Python", "C++"])
def test_get_item_name_is_not_a_code(code):
    with pytest.raises(ValueError, match="usa search_catalog"):
        get_item(code)
