import pytest

from assistant.mcp_client import PromptArgument, PromptInfo
from assistant.prompts import (
    PromptCommandError,
    format_prompt_list,
    parse_prompt_command,
    prompt_log_line,
    prompt_messages,
)

P = [
    PromptInfo(
        "spiega",
        "Spiega un argomento al livello richiesto.",
        (
            PromptArgument("argomento", "concetto da spiegare", True),
            PromptArgument("livello", "base, intermedio o avanzato", False),
        ),
    ),
    PromptInfo(
        "riassumi_conversazione",
        "Riassume i turni della sessione corrente.",
        (PromptArgument("stile", "sintetico o dettagliato", False),),
    ),
]


def test_comando_valido_con_virgolette():
    assert parse_prompt_command(
        ' spiega argomento="Model Context Protocol" livello=base', P
    ) == ("spiega", {"argomento": "Model Context Protocol", "livello": "base"})


def test_apostrofo_e_caratteri_italiani():
    assert parse_prompt_command("spiega argomento=l'IA", P)[1] == {"argomento": "l'IA"}
    assert parse_prompt_command('spiega argomento="perché «MCP»?"', P)[1] == {
        "argomento": "perché «MCP»?"
    }


@pytest.mark.parametrize("rest", ["spiega argomento=", 'spiega argomento=""'])
def test_valore_vuoto_passa(rest):
    assert parse_prompt_command(rest, P) == ("spiega", {"argomento": ""})


@pytest.mark.parametrize(
    "rest, messaggio",
    [
        ("", "Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)"),
        ("   ", "Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)"),
        ('spiega argomento="MCP', "Virgolette non chiuse: controlla il comando."),
        (
            "spiegami",
            "Prompt sconosciuto: spiegami. Disponibili: spiega, riassumi_conversazione.",
        ),
        (
            "spiega MCP",
            "Argomento non valido: 'MCP'. Usa nome=valore, per esempio "
            'argomento="Model Context Protocol".',
        ),
        (
            "spiega =x",
            "Argomento non valido: '=x'. Usa nome=valore, per esempio "
            'argomento="Model Context Protocol".',
        ),
        ("spiega argomento=a argomento=b", "Argomento ripetuto per spiega: argomento."),
        (
            "spiega tema=x",
            "Argomento sconosciuto per spiega: tema (ammessi: argomento, livello).",
        ),
        (
            "spiega livello=base",
            "Argomento obbligatorio mancante per spiega: argomento.",
        ),
    ],
)
def test_errori(rest, messaggio):
    with pytest.raises(PromptCommandError) as e:
        parse_prompt_command(rest, P)
    assert str(e.value) == messaggio


def test_nome_prompt_esatto_maiuscole():
    with pytest.raises(PromptCommandError):
        parse_prompt_command("Spiega argomento=x", P)


def test_elenco():
    assert format_prompt_list(P) == "\n".join(
        [
            "spiega — Spiega un argomento al livello richiesto.",
            "  argomento (obbligatorio): concetto da spiegare",
            "  livello (facoltativo): base, intermedio o avanzato",
            "riassumi_conversazione — Riassume i turni della sessione corrente.",
            "  stile (facoltativo): sintetico o dettagliato",
        ]
    )


def test_elenco_vuoto():
    assert format_prompt_list([]) == "Nessun prompt disponibile sul server."


def test_messaggi():
    assert prompt_messages([("user", "a"), ("assistant", "b"), ("system", "c")]) == [
        {"ruolo": "utente", "contenuto": "a"},
        {"ruolo": "assistente", "contenuto": "b"},
    ]


def test_riga_di_log():
    assert (
        prompt_log_line("spiega", {"argomento": "MCP"}, [("user", "Spiegami\n«MCP»")])
        == '[prompt] spiega {"argomento": "MCP"} → Spiegami «MCP»'
    )
