"""Grafo LangGraph: stato, nodi e instradamento."""

import json
import logging
from collections.abc import Callable
from typing import Annotated, NotRequired, TypedDict

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ToolException
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from assistant.llm import REASONING_KEY
from assistant.reviewer import Review, feedback_message, is_review_feedback, last_question_index
from assistant.router import Route, refusal_text

logger = logging.getLogger("assistant.graph")

LIMIT_MESSAGE = "Limite di passaggi raggiunto: prova a riformulare la domanda o chiedimi altro."


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int
    route: NotRequired[str]
    route_reason: NotRequired[str]  # serve al nodo refusal per il testo del rifiuto
    reviews: NotRequired[int]
    review_outcome: NotRequired[str]  # approved, retry, limit o invalid
    review_reason: NotRequired[str]


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
        "Per giorni della settimana, festività e scadenze usa `date_info`, `find_holiday`, `add_days` e "
        "`days_between`, con le date nel formato AAAA-MM-GG; riporta anche gli avvisi degli strumenti, "
        "per esempio che una festività è già passata. "
        "Per sapere quanti giorni mancano a una data o a una festività non contare tu i giorni: riporta il numero "
        "dato dagli strumenti (per esempio «fra N giorni») oppure chiama `days_between`. "
        "Per qualsiasi domanda su un linguaggio di programmazione (chi l'ha creato, anno, paradigmi...) "
        "chiama sempre gli strumenti del catalogo prima di rispondere; non dire mai che un dato non c'è senza "
        "averlo cercato. Se l'utente indica un codice (es. XYZ), chiama subito `get_item` con quel codice. "
        "Per domande sui linguaggi di programmazione usa `search_catalog` con poche parole chiave al singolare "
        "quando non conosci il codice, poi `get_item` con il codice trovato; rispondi solo con i dati restituiti "
        "dagli strumenti e di' chiaramente quando un dato non è nel catalogo; se la ricerca dice che ci sono altri "
        "risultati e ti servono tutti, ripetila con `max_results` più alto. "
        "Per salvare una nota DEVI chiamare `add_note`, una sola volta per richiesta: la nota esiste solo se "
        "lo strumento risponde «Nota N salvata», quindi non scrivere mai di averla salvata senza quella "
        "risposta. La scadenza va nel formato AAAA-MM-GG; se l'utente indica un giorno della settimana "
        "(es. «venerdì») o «domani», non chiedergli la data: ricavala tu con `get_current_time` e `add_days`, "
        "poi chiama `add_note`. Per vedere le note usa `list_notes`. Per eliminare una nota usa `delete_note` "
        "con l'ID esatto preso da `list_notes`; se non è chiaro quale nota intende l'utente, chiediglielo; "
        "prima di eliminare il programma chiederà conferma all'utente. Non dire mai che una nota è stata "
        "eliminata se lo strumento non lo conferma. "
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
        logger.debug("[strumento] %s call_id=%s argomenti=%s esito=%s → %s", call["name"], message.tool_call_id,
                    json.dumps(call["args"], ensure_ascii=False), outcome, message.content)


def cleanup_review(messages: list[AnyMessage]) -> list[RemoveMessage]:
    # Toglie ogni indicazione del revisore e la bozza bocciata subito prima; chiamate e risultati degli strumenti restano
    removed = []
    for i, m in enumerate(messages):
        if is_review_feedback(m):
            removed.append(RemoveMessage(id=m.id))
            if i > 0:
                removed.append(RemoveMessage(id=messages[i - 1].id))
    return removed


def build_graph(model: BaseChatModel, tools: list[BaseTool], max_steps: int,
                answer_check: Callable[[list[AnyMessage]], list[str]] | None = None,
                router: Callable[[list[AnyMessage]], Route] | None = None,
                reviewer: Callable[[str, str], Review] | None = None, max_reviews: int = 3):
    model_with_tools = model.bind_tools(tools)
    # Gli errori dello strumento tornano al modello come ToolMessage con stato "error".
    # Niente wrap_tool_call: con un wrapper il ToolNode convertirebbe in messaggio anche gli errori di collegamento
    tool_node = ToolNode(tools, handle_tool_errors=tool_error_message)

    def model_node(state: State) -> dict:
        steps = state["steps"] + 1
        logger.debug("[grafo] nodo model: passaggio %d/%d", steps, max_steps)
        response = model_with_tools.invoke(state["messages"])
        if REASONING_KEY in response.additional_kwargs:
            # Il ragionamento si mostra in streaming ma non entra nella cronologia
            extra = {k: v for k, v in response.additional_kwargs.items() if k != REASONING_KEY}
            response = response.model_copy(update={"additional_kwargs": extra})
        return {"messages": [response], "steps": steps}

    def route_after_model(state: State) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            if reviewer and isinstance(last.content, str) and last.content.strip():
                target = "reviewer"
            else:
                target = "answer_check" if answer_check else END
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
        last_human = last_question_index(messages)
        removed = messages[last_human + 1:]
        logger.debug("[grafo] nodo step_limit: rimossi %d messaggi", len(removed))
        for m in removed:
            detail = m.tool_calls if isinstance(m, AIMessage) and m.tool_calls else m.content
            logger.debug("[grafo] messaggio rimosso: %s %s", type(m).__name__, detail)
        return {"messages": [RemoveMessage(id=m.id) for m in removed] + [AIMessage(LIMIT_MESSAGE)]}

    def answer_check_node(state: State) -> dict:
        # Controllo facoltativo: non richiama il modello e non cambia steps; sostituisce solo l'ultima risposta (stesso id)
        last = state["messages"][-1]
        if not isinstance(last.content, str):
            return {}
        warnings = answer_check(state["messages"])
        if not warnings:
            return {}
        logger.info("[controllo] falso successo: avviso all'utente → %s", " | ".join(warnings))
        return {"messages": [AIMessage(content=last.content + "\n\n" + "\n".join(warnings), id=last.id)]}

    def reviewer_node(state: State) -> dict:
        messages = state["messages"]
        reviews = state.get("reviews", 0)
        question = messages[last_question_index(messages)].content
        try:
            result = reviewer(question, messages[-1].content)
        except (OutputParserException, ValueError) as error:
            # Giudizio non valido: nel dubbio la risposta passa
            logger.warning("[revisore] risposta non valida (%s): risposta approvata", error)
            return {"messages": cleanup_review(messages), "review_outcome": "invalid", "review_reason": "",
                    "reviews": reviews}
        # Il motivo va in una riga del terminale e nell'indicazione all'agente: una riga sola, mai vuoto
        reason = " ".join(result.motivo.split()) or "il motivo non è stato indicato"
        # DEBUG: lo streaming mostra già il verdetto all'utente
        logger.debug("[revisore] coerente=%s motivo=%s revisione %d/%d", "sì" if result.coerente else "no", reason,
                    reviews, max_reviews)
        if result.coerente:
            return {"messages": cleanup_review(messages), "review_outcome": "approved", "review_reason": reason,
                    "reviews": reviews}
        if reviews < max_reviews:
            # Nuovo tentativo: i passaggi ripartono da zero
            return {"messages": [feedback_message(reason)], "steps": 0, "reviews": reviews + 1,
                    "review_outcome": "retry", "review_reason": reason}
        logger.debug("[revisore] limite raggiunto (%d revisioni): resta l'ultima risposta", reviews)
        return {"messages": cleanup_review(messages), "review_outcome": "limit", "review_reason": reason,
                "reviews": reviews}

    def route_after_reviewer(state: State) -> str:
        if state["review_outcome"] == "retry":
            return "model"
        return "answer_check" if answer_check else END

    def router_node(state: State) -> dict:
        try:
            result = router(state["messages"])
        except (OutputParserException, ValueError) as error:
            # Risposta non valida del classificatore: nel dubbio decide l'agente
            logger.warning("[router] risposta non valida (%s): la domanda passa all'agente", error)
            return {"route": "conversazione", "route_reason": ""}
        target = "agente" if result.categoria == "conversazione" else "rifiuto"
        logger.info("[router] categoria=%s motivo=%s → %s", result.categoria, " ".join(result.motivo.split()), target)
        return {"route": result.categoria, "route_reason": result.motivo}

    def route_after_router(state: State) -> str:
        return "model" if state["route"] == "conversazione" else "refusal"

    def refusal_node(state: State) -> dict:
        route = Route(categoria="fuori_ambito", motivo=state["route_reason"])
        return {"messages": [AIMessage(refusal_text(route))]}

    graph = StateGraph(State)
    graph.add_node("model", model_node)
    graph.add_node("tools", tools_node)
    graph.add_node("step_limit", step_limit_node)
    if router:
        graph.add_node("router", router_node)
        graph.add_node("refusal", refusal_node)
        graph.add_edge(START, "router")
        graph.add_conditional_edges("router", route_after_router, ["model", "refusal"])
        graph.add_edge("refusal", END)
    else:
        graph.add_edge(START, "model")
    destinations = ["tools", "step_limit", END]
    if reviewer:
        graph.add_node("reviewer", reviewer_node)
        graph.add_conditional_edges("reviewer", route_after_reviewer,
                                    ["model", END] + (["answer_check"] if answer_check else []))
        destinations.append("reviewer")
    if answer_check:
        graph.add_node("answer_check", answer_check_node)
        graph.add_edge("answer_check", END)
        destinations.append("answer_check")
    graph.add_conditional_edges("model", route_after_model, destinations)
    graph.add_edge("tools", "model")
    graph.add_edge("step_limit", END)
    return graph.compile()
