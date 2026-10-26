"""Grafo LangGraph: stato, nodi e instradamento."""

import logging
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

logger = logging.getLogger("assistant.graph")

LIMIT_MESSAGE = "Limite di passaggi raggiunto: prova a riformulare la domanda o chiedimi altro."


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int


def system_prompt(default_timezone: str) -> str:
    return (
        "Sei l'assistente del laboratorio. Rispondi sempre in italiano, in modo chiaro e conciso. "
        "Quando l'utente ti saluta, presentati brevemente. "
        "Quando l'utente chiede l'ora o la data, usa sempre lo strumento `get_current_time`, non inventarla. "
        f"Se l'utente non indica un fuso orario usa `{default_timezone}`; "
        "dopo aver risposto chiedi se gli serve l'ora di un altro fuso orario. "
        "Se indica una città o un paese, passa allo strumento il nome IANA corrispondente "
        "(per esempio Tokyo → Asia/Tokyo)."
    )


def build_graph(model: BaseChatModel, tools: list[BaseTool], max_steps: int):
    model_with_tools = model.bind_tools(tools)

    def model_node(state: State) -> dict:
        steps = state["steps"] + 1
        logger.debug("[grafo] nodo model: passaggio %d/%d", steps, max_steps)
        response = model_with_tools.invoke(state["messages"])
        return {"messages": [response], "steps": steps}

    def route_after_model(state: State) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            target = END
        elif state["steps"] < max_steps:
            target = "tools"
        else:
            target = "step_limit"
        logger.debug("[grafo] instradamento dopo model: %s (steps=%d/%d)", target, state["steps"], max_steps)
        return target

    def step_limit_node(state: State) -> dict:
        logger.info("[grafo] limite di passaggi raggiunto (%d/%d)", state["steps"], max_steps)
        messages = state["messages"]
        last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        removed = messages[last_human + 1:]
        logger.debug("[grafo] nodo step_limit: rimossi %d messaggi", len(removed))
        return {"messages": [RemoveMessage(id=m.id) for m in removed] + [AIMessage(LIMIT_MESSAGE)]}

    graph = StateGraph(State)
    graph.add_node("model", model_node)
    # handle_tool_errors=True: gli errori dello strumento tornano al modello come ToolMessage
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    graph.add_node("step_limit", step_limit_node)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", "step_limit", END])
    graph.add_edge("tools", "model")
    graph.add_edge("step_limit", END)
    return graph.compile()
