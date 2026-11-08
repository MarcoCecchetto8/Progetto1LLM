"""Modello e strumento finti per i test del grafo (nessun modello reale, nessun server MCP)."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException, tool


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def tool_call(args: dict, id: str, name: str = "get_current_time") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])


def fake(*msgs: AIMessage) -> FakeToolModel:
    return FakeToolModel(messages=iter(msgs))


FAKE_TIMES = {"Europe/Rome": "Europe/Rome: 2026-10-26T14:32:05+01:00",
              "Asia/Tokyo": "Asia/Tokyo: 2026-10-26T22:32:05+09:00"}


@tool
def fake_clock(timezone: str | None = None) -> str:
    """Orologio finto con istante fisso, come quello del server MCP."""
    name = timezone or "Europe/Rome"
    if name not in FAKE_TIMES:
        raise ToolException(f'Fuso orario sconosciuto: "{name}". Usa un nome IANA, es. Europe/Rome.')
    return FAKE_TIMES[name]


fake_clock.name = "get_current_time"
