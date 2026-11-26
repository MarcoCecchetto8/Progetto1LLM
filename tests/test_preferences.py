from pathlib import Path

from lab_server.preferences import Preferences, parse_preferences

RIS = "Europe/Rome"
DEFAULT = Preferences("italiano", RIS, "sintetico")


def test_all_valid():
    text = '{"lingua": "inglese", "fuso_orario": "America/New_York", "stile": "dettagliato"}'
    assert parse_preferences(text, RIS) == (
        Preferences("inglese", "America/New_York", "dettagliato"),
        [],
    )


def test_unavailable():
    assert parse_preferences(None, RIS, "file mancante") == (
        DEFAULT,
        ["resource non disponibile (file mancante): uso italiano, sintetico, Europe/Rome"],
    )


def test_deeply_nested_json_is_invalid():
    assert parse_preferences("[" * 100000, RIS) == (
        DEFAULT,
        ["contenuto non valido (JSON non leggibile): uso italiano, sintetico, Europe/Rome"],
    )


def test_invalid_json():
    assert parse_preferences("{", RIS) == (
        DEFAULT,
        ["contenuto non valido (JSON non leggibile): uso italiano, sintetico, Europe/Rome"],
    )


def test_not_an_object():
    assert parse_preferences("[1, 2]", RIS) == (
        DEFAULT,
        ["contenuto non valido (non è un oggetto JSON): uso italiano, sintetico, Europe/Rome"],
    )


def test_single_invalid_field_keeps_others():
    text = '{"lingua": "inglese", "fuso_orario": "America/New_York", "stile": "medio"}'
    assert parse_preferences(text, RIS) == (
        Preferences("inglese", "America/New_York", "sintetico"),
        ["stile 'medio' non ammesso: uso 'sintetico'"],
    )


def test_unknown_timezone_uses_fallback():
    text = '{"lingua": "inglese", "fuso_orario": "Marte/Base", "stile": "dettagliato"}'
    assert parse_preferences(text, RIS) == (
        Preferences("inglese", RIS, "dettagliato"),
        ["fuso_orario 'Marte/Base' non ammesso: uso 'Europe/Rome'"],
    )


def test_missing_field():
    text = '{"fuso_orario": "Europe/Rome", "stile": "sintetico"}'
    assert parse_preferences(text, RIS) == (DEFAULT, ["lingua mancante: uso 'italiano'"])


def test_non_string_values():
    text = '{"lingua": null, "fuso_orario": 5, "stile": ["x"]}'
    prefs, warnings = parse_preferences(text, RIS)
    assert prefs == DEFAULT
    assert warnings == [
        "lingua 'None' non ammesso: uso 'italiano'",
        "fuso_orario '5' non ammesso: uso 'Europe/Rome'",
        "stile '['x']' non ammesso: uso 'sintetico'",
    ]


def test_case_sensitive():
    text = '{"lingua": "Inglese", "fuso_orario": "Europe/Rome", "stile": "sintetico"}'
    assert parse_preferences(text, RIS) == (
        DEFAULT,
        ["lingua 'Inglese' non ammesso: uso 'italiano'"],
    )


def test_extra_fields_ignored():
    text = '{"lingua": "italiano", "fuso_orario": "Europe/Rome", "stile": "sintetico", "tema": "scuro"}'
    assert parse_preferences(text, RIS) == (DEFAULT, [])


def test_default_file_is_valid():
    path = Path(__file__).resolve().parent.parent / "config" / "preferenze.json"
    assert parse_preferences(path.read_text(encoding="utf-8"), RIS) == (DEFAULT, [])
