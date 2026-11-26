"""Dipendenze ridotte delle immagini Docker: stesse versioni dell'elenco completo."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _pins(path: Path) -> dict[str, str]:
    """Nome del pacchetto (minuscolo, senza extra) → riga intera, senza commenti e righe vuote."""
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[\[=<>~!]", line, maxsplit=1)[0].strip().lower()
        pins[name] = line
    return pins


@pytest.mark.parametrize("name", ["requirements-backend.txt", "requirements-frontend.txt"])
def test_image_requirements_match_full_list(name):
    full = _pins(ROOT / "requirements.txt")
    for package, line in _pins(ROOT / name).items():
        assert full.get(package) == line, f"{name}: «{line}» diversa da requirements.txt"


def test_image_requirements_content():
    assert set(_pins(ROOT / "requirements-backend.txt")) == {"fastapi", "uvicorn", "httpx", "psycopg", "python-dotenv"}
    assert set(_pins(ROOT / "requirements-frontend.txt")) == {"fastapi", "uvicorn", "python-dotenv"}
