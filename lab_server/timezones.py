"""Fusi orari IANA ammessi: gli stessi su Windows e Linux."""

from functools import cache
from importlib.resources import files
from zoneinfo import ZoneInfo


@cache
def known_timezones() -> frozenset[str]:
    # L'elenco del pacchetto tzdata (versione fissata) non dipende dal sistema: i fusi del
    # sistema operativo e le regole dei percorsi di Windows cambierebbero i nomi accettati
    return frozenset(files("tzdata").joinpath("zones").read_text(encoding="utf-8").split())


def get_timezone(name: str) -> ZoneInfo | None:
    """Il fuso con questo nome IANA esatto, oppure None se il nome non è nell'elenco."""
    return ZoneInfo(name) if name in known_timezones() else None
