from pathlib import Path

import pytest

from assistant.config import ConfigError, load_scope, load_settings

BASE = {"LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_MODEL": "google/gemma-4-e2b"}


def test_defaults():
    s = load_settings(BASE)
    assert (s.timeout, s.temperature, s.max_steps, s.default_timezone, s.log_level) == (120.0, 0.2, 5, "Europe/Rome", "INFO")


@pytest.mark.parametrize("missing", ["LMSTUDIO_BASE_URL", "LMSTUDIO_MODEL"])
def test_missing_required(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_blank_required_counts_as_missing():
    with pytest.raises(ConfigError, match="LMSTUDIO_MODEL"):
        load_settings({**BASE, "LMSTUDIO_MODEL": "  "})


@pytest.mark.parametrize("var,value", [("MAX_STEPS", "0"), ("MAX_STEPS", "abc"), ("LMSTUDIO_TIMEOUT", "-1"),
    ("LMSTUDIO_TEMPERATURE", "x"), ("DEFAULT_TIMEZONE", "Marte/Base"), ("LOG_LEVEL", "LOUD")])
def test_invalid_values(var, value):
    with pytest.raises(ConfigError, match=var):
        load_settings({**BASE, var: value})


# Nomi lunghissimi (OSError) o accettati solo da un sistema: Windows ignora punto finale,
# "\" e "::$DATA" nei percorsi, Linux ha "posixrules" tra i fusi di sistema
@pytest.mark.parametrize("value", ["x" * 300, "Europe/Rome.", "Europe\\Rome", "Europe/Rome::$DATA", "posixrules"])
def test_timezone_not_iana(value):
    with pytest.raises(ConfigError, match="DEFAULT_TIMEZONE"):
        load_settings({**BASE, "DEFAULT_TIMEZONE": value})


def test_overrides_and_log_level_case():
    s = load_settings({**BASE, "MAX_STEPS": "3", "DEFAULT_TIMEZONE": "Asia/Tokyo", "LOG_LEVEL": "debug"})
    assert (s.max_steps, s.default_timezone, s.log_level) == (3, "Asia/Tokyo", "DEBUG")


def test_notes_service_url_default_and_normalized():
    base = {"LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_MODEL": "m"}
    assert load_settings(base).notes_service_url == ""
    assert load_settings({**base, "NOTES_SERVICE_URL": " http://notes:8000/ "}).notes_service_url == "http://notes:8000"


@pytest.mark.parametrize("value,expected", [(None, True), ("true", True), ("TRUE", True), (" True ", True),
                                            ("false", False), ("False", False)])
def test_show_reasoning(value, expected):
    env = {**BASE} if value is None else {**BASE, "SHOW_REASONING": value}
    assert load_settings(env).show_reasoning is expected


def test_show_reasoning_invalid():
    with pytest.raises(ConfigError, match=r"SHOW_REASONING non valida: 'forse' \(valori ammessi: true, false\)\."):
        load_settings({**BASE, "SHOW_REASONING": "forse"})


def test_scope_file_default_and_override():
    assert load_settings(BASE).scope_file == "config/ambito.txt"
    assert load_settings({**BASE, "SCOPE_FILE": "altro.txt"}).scope_file == "altro.txt"


def test_load_scope_relative_and_absolute(tmp_path):
    (tmp_path / "a.txt").write_text("  Ambito di prova \n", encoding="utf-8")
    assert load_scope("a.txt", tmp_path) == "Ambito di prova"
    assert load_scope(str(tmp_path / "a.txt"), Path("/altrove")) == "Ambito di prova"


def test_load_scope_missing_or_blank(tmp_path):
    (tmp_path / "vuoto.txt").write_text("  \n ", encoding="utf-8")
    for name in ("manca.txt", "vuoto.txt"):
        with pytest.raises(ConfigError, match="SCOPE_FILE non valida"):
            load_scope(name, tmp_path)


def test_real_scope_file():
    text = load_scope("config/ambito.txt", Path(__file__).resolve().parent.parent)
    assert text and "Esempi:" in text


@pytest.mark.parametrize("value,expected", [(None, 3), ("0", 0), ("5", 5)])
def test_max_reviews(value, expected):
    env = {**BASE} if value is None else {**BASE, "MAX_REVIEWS": value}
    assert load_settings(env).max_reviews == expected


@pytest.mark.parametrize("value", ["-1", "abc"])
def test_max_reviews_invalid(value):
    with pytest.raises(ConfigError, match="MAX_REVIEWS"):
        load_settings({**BASE, "MAX_REVIEWS": value})


@pytest.mark.parametrize("env,threshold,keep", [({}, 4000, 2), ({"SUMMARY_THRESHOLD": "1500"}, 1500, 2),
                                               ({"SUMMARY_KEEP_TURNS": "3"}, 4000, 3)])
def test_summary_settings(env, threshold, keep):
    s = load_settings({**BASE, **env})
    assert (s.summary_threshold, s.summary_keep_turns) == (threshold, keep)


@pytest.mark.parametrize("var", ["SUMMARY_THRESHOLD", "SUMMARY_KEEP_TURNS"])
@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_summary_settings_invalid(var, value):
    with pytest.raises(ConfigError, match=var):
        load_settings({**BASE, var: value})
