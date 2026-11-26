"""Compattazione una tantum dei numeri delle note: 1…N in ordine di numero. Da lanciare a servizio spento."""

import argparse
from pathlib import Path

from notes_service.__main__ import DEFAULT_DB
from notes_service.store import NoteStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m notes_service.compact",
        description="Rinumera le note a 1…N in ordine di numero (servizio delle note spento).",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="file SQLite delle note")
    args = parser.parse_args(argv)
    changed = NoteStore(args.db).compact()
    if not changed:
        print("Nessuna nota da rinumerare.")
    for old_id, new_id in changed:
        print(f"{old_id} → {new_id}")


if __name__ == "__main__":
    main()
