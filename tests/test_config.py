import pytest

from assistant.config import ConfigError, load_settings

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


def test_overrides_and_log_level_case():
    s = load_settings({**BASE, "MAX_STEPS": "3", "DEFAULT_TIMEZONE": "Asia/Tokyo", "LOG_LEVEL": "debug"})
    assert (s.max_steps, s.default_timezone, s.log_level) == (3, "Asia/Tokyo", "DEBUG")
