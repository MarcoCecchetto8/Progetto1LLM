"""Modello finto per i test del grafo (nessun modello reale)."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def tool_call(args: dict, id: str) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": "get_current_time", "args": args, "id": id}])


def fake(*msgs: AIMessage) -> FakeToolModel:
    return FakeToolModel(messages=iter(msgs))
