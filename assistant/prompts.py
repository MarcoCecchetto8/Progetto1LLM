"""Comandi /prompts e /prompt: analisi, controllo e testi (nessun I/O)."""

import json

from assistant.mcp_client import PromptInfo

USO = "Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)"


class PromptCommandError(Exception):
    """Errore di analisi o controllo: il messaggio è il testo da mostrare."""


def format_prompt_list(prompts: list[PromptInfo]) -> str:
    if not prompts:
        return "Nessun prompt disponibile sul server."
    righe = []
    for p in prompts:
        righe.append(f"{p.name} — {p.description}")
        for a in p.arguments:
            tipo = "obbligatorio" if a.required else "facoltativo"
            righe.append(f"  {a.name} ({tipo}): {a.description}")
    return "\n".join(righe)


def _split(rest: str) -> list[str]:
    """Divide sugli spazi; solo le virgolette doppie raggruppano (si tolgono)."""
    tokens: list[str] = []
    current: list[str] = []
    in_token = False
    in_quotes = False
    for ch in rest:
        if ch == '"':
            in_quotes = not in_quotes
            in_token = True
        elif ch.isspace() and not in_quotes:
            if in_token:
                tokens.append("".join(current))
                current, in_token = [], False
        else:
            current.append(ch)
            in_token = True
    if in_quotes:
        raise PromptCommandError("Virgolette non chiuse: controlla il comando.")
    if in_token:
        tokens.append("".join(current))
    return tokens


def parse_prompt_command(
    rest: str, prompts: list[PromptInfo]
) -> tuple[str, dict[str, str]]:
    if not rest.strip():
        raise PromptCommandError(USO)
    tokens = _split(rest)
    if not tokens or not tokens[0]:
        raise PromptCommandError(USO)
    name, items = tokens[0], tokens[1:]
    info = next((p for p in prompts if p.name == name), None)
    if info is None:
        elenco = ", ".join(p.name for p in prompts)
        raise PromptCommandError(f"Prompt sconosciuto: {name}. Disponibili: {elenco}.")
    pairs = []
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise PromptCommandError(
                f"Argomento non valido: '{item}'. Usa nome=valore, per esempio "
                'argomento="Model Context Protocol".'
            )
        pairs.append((key, value))
    arguments: dict[str, str] = {}
    for key, value in pairs:
        if key in arguments:
            raise PromptCommandError(f"Argomento ripetuto per {name}: {key}.")
        arguments[key] = value
    ammessi = [a.name for a in info.arguments]
    for key in arguments:
        if key not in ammessi:
            raise PromptCommandError(
                f"Argomento sconosciuto per {name}: {key} "
                f"(ammessi: {', '.join(ammessi)})."
            )
    for a in info.arguments:
        if a.required and a.name not in arguments:
            raise PromptCommandError(
                f"Argomento obbligatorio mancante per {name}: {a.name}."
            )
    return name, arguments


ROLES = {"user": "utente", "assistant": "assistente"}


def prompt_messages(messages: list[tuple[str, str]]) -> list[dict]:
    """Messaggi nel formato dell'API dell'agente; i ruoli diversi da utente e assistente si scartano."""
    return [{"ruolo": ROLES[role], "contenuto": text} for role, text in messages if role in ROLES]


def prompt_log_line(
    name: str, arguments: dict[str, str], messages: list[tuple[str, str]]
) -> str:
    primo = " ".join(messages[0][1].split()) if messages else ""
    return f"[prompt] {name} {json.dumps(arguments, ensure_ascii=False)} → {primo}"
