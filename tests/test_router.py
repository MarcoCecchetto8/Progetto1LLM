from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from assistant.router import (REFUSAL, ROUTER_CONTEXT_MESSAGES, ROUTER_INSTRUCTIONS, Route, build_router,
                              refusal_text, router_context, router_prompt)


class FakeStructured:
    def __init__(self, owner):
        self.owner = owner

    def invoke(self, messages):
        self.owner.invoked = messages
        return Route(categoria="fuori_ambito", motivo="cucina")


class FakeModel:
    def model_copy(self, update):
        self.update = update
        return self

    def with_structured_output(self, schema, method):
        self.schema = schema
        self.method = method
        return FakeStructured(self)


def test_router_prompt():
    prompt = router_prompt("X")
    assert prompt.startswith(ROUTER_INSTRUCTIONS)
    assert prompt.endswith("X")
    assert prompt == ROUTER_INSTRUCTIONS + "\n\nX"


def test_router_context_filters_tool_traffic():
    messages = [
        SystemMessage("sistema"),
        HumanMessage("Che ore sono a Roma?"),
        AIMessage("", tool_calls=[{"name": "clock", "args": {}, "id": "1"}]),
        ToolMessage("10:00", tool_call_id="1"),
        AIMessage("Sono le 10."),
        HumanMessage("e a Tokyo?"),
    ]
    assert router_context(messages) == [
        HumanMessage("Che ore sono a Roma?"), AIMessage("Sono le 10."), HumanMessage("e a Tokyo?")]


def test_router_context_keeps_last_messages():
    messages = []
    for i in range(10):
        messages += [HumanMessage(f"d{i}"), AIMessage(f"r{i}")]
    context = router_context(messages)
    assert len(context) == ROUTER_CONTEXT_MESSAGES == 6
    assert context == messages[-6:]


def test_build_router():
    model = FakeModel()
    route = build_router(model, "AMBITO")
    history = [SystemMessage("s"), HumanMessage("Come si fa il tiramisù?")]
    result = route(history)
    assert model.update == {"reasoning_effort": "none"}
    assert model.schema is Route
    assert model.method == "json_schema"
    assert model.invoked == [SystemMessage(router_prompt("AMBITO")), HumanMessage("Come si fa il tiramisù?")]
    assert result == Route(categoria="fuori_ambito", motivo="cucina")


def test_refusal_text():
    route = Route(categoria="fuori_ambito", motivo="cucina")
    assert refusal_text(route) == REFUSAL.format(motivo="cucina")


def test_route_schema_enum():
    schema = Route.model_json_schema()
    assert schema["properties"]["categoria"]["enum"] == ["conversazione", "fuori_ambito"]
