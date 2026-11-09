"""Catalogo dei linguaggi di programmazione: ricerca per parole e dettaglio per codice."""

import json
import re
import unicodedata
from functools import cache
from importlib.resources import files

MAX_RESULTS = 20
DEFAULT_RESULTS = 5

# Parole vuote: tolte solo dalla query, mai dai campi
STOP_WORDS = frozenset(
    "a al alla che chi con creato da dal dei del della delle di e gli ha i il in la le "
    "linguaggi linguaggio lo nato nati nel o per programmazione quale quali sono un una".split()
)


def _words(text: str) -> list[str]:
    # Senza accenti e maiuscole; "+" e "#" restano attaccati alla parola (C++, C#)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.findall(r"[0-9a-z]+[+#]*", text.casefold())


@cache
def _catalog() -> list[dict]:
    return json.loads(files("lab_server").joinpath("catalog.json").read_text(encoding="utf-8"))


@cache
def _index() -> list[tuple[dict, frozenset[str]]]:
    return [
        (
            entry,
            frozenset(
                _words(
                    " ".join(
                        [entry["code"], entry["name"], str(entry["year"]),
                         *entry["authors"], *entry["paradigms"], entry["description"]]
                    )
                )
            ),
        )
        for entry in _catalog()
    ]


def search(query: str, max_results: int = DEFAULT_RESULTS) -> str:
    words = {w for w in _words(query) if w not in STOP_WORDS}
    if not words:
        raise ValueError("La ricerca richiede almeno una parola chiave (es. funzionale, Haskell).")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results deve essere compreso fra 1 e {MAX_RESULTS}.")
    q = query.strip()
    found = [(len(words & fields), entry) for entry, fields in _index() if words & fields]
    if not found:
        return f'Nessun linguaggio corrisponde a "{q}". Se hai usato parole al plurale riprova al singolare (es. funzionale); altrimenti il catalogo non lo contiene.'
    found.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
    n, m = len(found), min(len(found), max_results)
    if n == 1:
        header = f'Trovato 1 linguaggio per "{q}":'
    elif m < n:
        header = f'Trovati {n} linguaggi per "{q}", mostrati {m}:'
    else:
        header = f'Trovati {n} linguaggi per "{q}":'
    lines = [header]
    lines += [f"- {e['code']}: {e['name']} ({e['year']})" for _, e in found[:m]]
    if m < n:
        lines.append(f"Ci sono altri {n - m} risultati: ripeti la ricerca con max_results più alto.")
    lines.append("Usa get_item con il codice per i dettagli.")
    return "\n".join(lines)


def get_item(code: str) -> str:
    key = code.strip()
    if not key:
        raise ValueError("Il codice è vuoto: usa search_catalog per trovare il codice.")
    entry = next((e for e in _catalog() if e["code"] == key.upper()), None)
    if entry is None:
        raise ValueError(f'Codice "{key}" non presente nel catalogo: usa search_catalog per trovare il codice.')
    return "\n".join([
        f"{entry['name']} ({entry['code']})",
        f"Anno: {entry['year']}",
        f"Autori: {', '.join(entry['authors'])}",
        f"Paradigmi: {', '.join(entry['paradigms'])}",
        f"Tipizzazione: {entry['typing']}",
        f"Descrizione: {entry['description']}",
    ])
