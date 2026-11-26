import asyncio
from datetime import UTC, datetime

import pytest
from fastmcp import Client

from lab_server.prompts import explain_text, summary_text
from lab_server.server import create_server

FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)


def call(action):
    async def main():
        async with Client(create_server("Europe/Rome", FIXED)) as client:
            return await action(client)
    return asyncio.run(main())


def test_explain_text_levels():
    assert explain_text("MCP") == "Spiegami «MCP» a livello base. Usa parole semplici, spiega i termini tecnici e fai un esempio concreto."
    assert explain_text("MCP", "intermedio") == "Spiegami «MCP» a livello intermedio. Dai per note le basi: spiega come funziona, con un esempio."
    assert explain_text(" MCP ", "avanzato") == "Spiegami «MCP» a livello avanzato. Entra nei dettagli tecnici: funzionamento interno, scelte di progetto e limiti."


def test_explain_text_errors():
    with pytest.raises(ValueError, match="^argomento vuoto: indica il concetto da spiegare$"):
        explain_text("  ")
    with pytest.raises(ValueError, match=r"^livello 'esperto' non ammesso \(ammessi: base, intermedio, avanzato\)$"):
        explain_text("MCP", "esperto")


def test_summary_text():
    prefix = "Riassumi la conversazione fin qui, basandoti solo sui messaggi precedenti e senza usare strumenti: "
    assert summary_text() == prefix + "in poche frasi, solo gli argomenti principali."
    assert summary_text("dettagliato") == prefix + "per ogni argomento, che cosa è stato chiesto e che cosa è stato risposto, in un breve elenco."
    with pytest.raises(ValueError, match=r"^stile 'lungo' non ammesso \(ammessi: sintetico, dettagliato\)$"):
        summary_text("lungo")


def test_list_prompts():
    prompts = {p.name: p for p in call(lambda c: c.list_prompts())}
    assert set(prompts) == {"spiega", "riassumi_conversazione"}
    assert prompts["spiega"].description == "Spiega un argomento al livello richiesto."
    assert prompts["riassumi_conversazione"].description == "Riassume i turni della sessione corrente."

    def args(name):
        return {a.name: (a.required, (a.description or "").split("\n\n")[0]) for a in prompts[name].arguments}

    assert args("spiega") == {"argomento": (True, "concetto da spiegare"),
                              "livello": (False, "base, intermedio o avanzato")}
    assert args("riassumi_conversazione") == {"stile": (False, "sintetico o dettagliato")}


def test_get_prompt_renders_text():
    result = call(lambda c: c.get_prompt("spiega", {"argomento": "MCP", "livello": "avanzato"}))
    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
    assert result.messages[0].content.text == explain_text("MCP", "avanzato")


def test_get_prompt_invalid_level_is_error():
    with pytest.raises(Exception, match="livello 'esperto' non ammesso"):
        call(lambda c: c.get_prompt("spiega", {"argomento": "MCP", "livello": "esperto"}))


def test_get_prompt_empty_argument_is_error():
    with pytest.raises(Exception, match="argomento vuoto"):
        call(lambda c: c.get_prompt("spiega", {"argomento": ""}))
