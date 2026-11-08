"""Grafo LangGraph: stato, nodi e instradamento."""

import json
import logging
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ToolException
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
        "Per ora, date, conversioni e calcoli usa sempre gli strumenti: non inventare i risultati. "
        "Quando l'utente chiede l'ora o la data, usa lo strumento `get_current_time`. "
        "Per le conversioni di unità usa `convert_units`. "
        "Per qualsiasi calcolo, anche semplice, chiama sempre `calculate`. "
        "Per un'equazione semplice riscrivila come espressione e chiama `calculate` con quella: "
        "per esempio per 2x = 28 chiama `calculate` con 28 / 2. "
        "Se uno strumento restituisce un errore, correggi gli argomenti oppure spiega l'errore all'utente. "
        f"Se l'utente non indica un fuso orario usa `{default_timezone}`; "
        "dopo aver risposto chiedi se gli serve l'ora di un altro fuso orario. "
        "Se indica una città o un paese, passa allo strumento il nome IANA corrispondente "
        "(per esempio Tokyo → Asia/Tokyo)."
    )


def tool_error_message(error: ToolException) -> str:
    # L'annotazione ToolException limita il ToolNode a questi errori: gli altri (es. server MCP caduto) escono dal grafo
    return f"Errore: {error}"


def log_tool_calls(calls: list[dict], messages: list) -> None:
    by_id = {call["id"]: call for call in calls}
    for message in messages:
        call = by_id.get(message.tool_call_id, {"name": message.name, "args": {}})
        outcome = "errore" if message.status == "error" else "ok"
        logger.info("[strumento] %s call_id=%s argomenti=%s esito=%s → %s", call["name"], message.tool_call_id,
                    json.dumps(call["args"], ensure_ascii=False), outcome, message.content)


def build_graph(model: BaseChatModel, tools: list[BaseTool], max_steps: int):
    model_with_tools = model.bind_tools(tools)
    # Gli errori dello strumento tornano al modello come ToolMessage con stato "error".
    # Niente wrap_tool_call: con un wrapper il ToolNode convertirebbe in messaggio anche gli errori di collegamento
    tool_node = ToolNode(tools, handle_tool_errors=tool_error_message)

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

    def tools_node(state: State, config: RunnableConfig) -> dict:
        result = tool_node.invoke(state, config)
        log_tool_calls(state["messages"][-1].tool_calls, result["messages"])
        return result

    def step_limit_node(state: State) -> dict:
        logger.info("[grafo] limite di passaggi raggiunto (%d/%d)", state["steps"], max_steps)
        messages = state["messages"]
        last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        removed = messages[last_human + 1:]
        logger.debug("[grafo] nodo step_limit: rimossi %d messaggi", len(removed))
        for m in removed:
            detail = m.tool_calls if isinstance(m, AIMessage) and m.tool_calls else m.content
            logger.debug("[grafo] messaggio rimosso: %s %s", type(m).__name__, detail)
        return {"messages": [RemoveMessage(id=m.id) for m in removed] + [AIMessage(LIMIT_MESSAGE)]}

    graph = StateGraph(State)
    graph.add_node("model", model_node)
    graph.add_node("tools", tools_node)
    graph.add_node("step_limit", step_limit_node)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", "step_limit", END])
    graph.add_edge("tools", "model")
    graph.add_edge("step_limit", END)
    return graph.compile()
