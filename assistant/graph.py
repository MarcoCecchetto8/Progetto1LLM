"""Grafo LangGraph: stato, nodi e instradamento."""

import datetime
import json
import logging
import re
from collections.abc import Callable
from typing import Annotated, NotRequired, TypedDict

import openai
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ToolException
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from assistant.llm import REASONING_KEY
from assistant.reviewer import Review, feedback_message, is_review_feedback, last_question_index
from assistant.router import Route, refusal_text, router_context
from assistant.summarizer import estimate_tokens, summary_cut, summary_line, transcript, with_summary
from lab_server.holidays import holiday_names, normalize_name
from lab_server.preferences import Preferences

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
    summary: NotRequired[str]  # riassunto in vigore: si aggiunge al prompt solo per la chiamata al modello
    summary_line: NotRequired[str]  # riga per il terminale, scritta quando il riassunto cambia
    decisions: NotRequired[dict[int, bool]]  # risposte dell'utente alle conferme, per ID della nota
    confirmations: NotRequired[list[dict]]  # conferme richieste: se non vuoto il turno è sospeso


STYLE_TEXTS = {
    "sintetico": "sintetico: rispondi in una o due frasi, solo con ciò che è chiesto",
    "dettagliato": ("dettagliato: aggiungi alla risposta il contesto utile preso dai risultati degli strumenti, "
                    "in qualche frase o in un breve elenco"),
}


# Il fuso orario non sta nel blocco: insieme alla riga dello stile il modello
# saltava get_current_time (3/6 contro 6/6 nella prova). Il fuso è nella frase
# delle istruzioni ed è il predefinito del server.
def preferences_block(preferences: Preferences) -> str:
    return (
        "Preferenze dell'utente (dalla resource utente://preferenze):\n"
        f"- Rispondi sempre in {preferences.lingua}.\n"
        f"- Stile: {STYLE_TEXTS[preferences.stile]}."
    )


def system_prompt(preferences: Preferences) -> str:
    return preferences_block(preferences) + "\n\n" + (
        "Sei l'assistente del laboratorio. "
        "Quando l'utente ti saluta, presentati brevemente. "
        "Ricorda quello che l'utente ti dice di sé in questa conversazione (per esempio il nome) e usalo "
        "quando te lo chiede: è nella cronologia, non è un dato privato da negare. "
        "Per ora, date, conversioni e calcoli usa sempre gli strumenti: non inventare i risultati. "
        "Non hai strumenti per meteo, notizie, prezzi o altri dati in tempo reale oltre a ora e data: se te li "
        "chiedono dillo chiaramente e non inventarli. "
        "Quando l'utente chiede l'ora o la data, usa lo strumento `get_current_time`. "
        "Per le conversioni di unità usa `convert_units`. "
        "Per qualsiasi calcolo, anche semplice, chiama sempre `calculate`. "
        "In italiano «per» è la moltiplicazione e «diviso» la divisione: «37 per 19» è 37 * 19, "
        "«37 diviso 19» è 37 / 19. "
        "Per un'equazione semplice riscrivila come espressione e chiama `calculate` con quella: "
        "per esempio per 2x = 28 chiama `calculate` con 28 / 2. "
        "Per giorni della settimana, festività e scadenze usa `date_info`, `find_holiday`, `add_days` e "
        "`days_between`, con le date nel formato AAAA-MM-GG; riporta anche gli avvisi degli strumenti, "
        "per esempio che una festività è già passata. "
        "Per quanti giorni mancano a una festività chiama `find_holiday` senza anno: se quest'anno è già passata "
        "ti dà la prossima, e conta la prossima, non quella passata. "
        "Per sapere quanti giorni mancano a una data o a una festività non contare tu i giorni: riporta il numero "
        "dato dagli strumenti (per esempio «fra N giorni») oppure chiama `days_between`. "
        "Per sapere che data sarà fra N giorni (o che data era N giorni fa) chiama `add_days`: non calcolarla tu. "
        "Per qualsiasi domanda su un linguaggio di programmazione (chi l'ha creato, anno, paradigmi...) "
        "chiama sempre gli strumenti del catalogo prima di rispondere; non dire mai che un dato non c'è senza "
        "averlo cercato. Se l'utente indica un codice (es. XYZ), chiama subito `get_item` con quel codice. "
        "Per domande sui linguaggi di programmazione usa `search_catalog` con poche parole chiave al singolare "
        "quando non conosci il codice, poi `get_item` con il codice trovato; rispondi solo con i dati restituiti "
        "dagli strumenti e di' chiaramente quando un dato non è nel catalogo; se la ricerca dice che ci sono altri "
        "risultati e ti servono tutti, ripetila con `max_results` più alto. "
        "Per salvare una nota DEVI chiamare `add_note`, una sola volta per richiesta: la nota esiste solo se "
        "lo strumento risponde «Nota N salvata», quindi non scrivere mai di averla salvata senza quella "
        "risposta. La scadenza va nel formato AAAA-MM-GG; se l'utente indica oggi, domani, dopodomani o un "
        "giorno della settimana (es. «venerdì»), non chiedergli la data e non calcolarla: passala così com'è "
        "in `due_date` (es. due_date=\"venerdì\"). Per vedere le note usa `list_notes` e riportale con il loro ID (es. «nota 4»), senza numerarle 1, 2, 3. Per eliminare una nota usa `delete_note` "
        "con l'ID esatto preso da `list_notes`; se non è chiaro quale nota intende l'utente, chiediglielo; "
        "prima di eliminare il programma chiederà conferma all'utente: non chiederla tu, chiama subito `delete_note`. Non dire mai che una nota è stata "
        "eliminata se lo strumento non lo conferma. "
        "Se uno strumento restituisce un errore, correggi gli argomenti oppure spiega l'errore all'utente. "
        f"Se l'utente non indica un fuso orario usa `{preferences.fuso_orario}`; "
        "dopo aver risposto chiedi se gli serve l'ora di un altro fuso orario. "
        "Se indica una città o un paese, passa allo strumento il nome IANA corrispondente "
        "(per esempio Tokyo → Asia/Tokyo)."
    )


_GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
         "novembre", "dicembre"]


def today_line(day: datetime.date, timezone: str) -> str:
    # Nomi da tabelle e non da locale/strftime: il risultato non dipende dal sistema
    return (f"Oggi è {_GIORNI[day.weekday()]} {day.day} {_MESI[day.month - 1]} {day.year} "
            f"({day.isoformat()}), fuso orario {timezone}.")


_NUMBER = r"\d+(?:[.,]\d+)?"
_PER_BETWEEN_NUMBERS = re.compile(rf"({_NUMBER})\s+per\s+(?={_NUMBER})")


def explain_multiplication(text: str) -> str:
    """«37 per 19» → «37 × 19»: il modello piccolo legge «per» come divisione. Con «dividi/dividere» non si tocca."""
    if re.search(r"\bdivid", text, re.IGNORECASE):
        return text
    return _PER_BETWEEN_NUMBERS.sub(r"\1 × ", text)


_RELATIVE_DAYS = re.compile(r"(?:fra|tra)\s+(\d{1,4})\s+giorni|(\d{1,4})\s+giorni\s+fa", re.IGNORECASE)


_HOLIDAY_QUESTION = re.compile(r"\bmanca(?:no)?\b", re.IGNORECASE)

# «che note ci sono?», «mostrami le note»: il modello a volte ricopiava l'elenco a memoria dalla chat
_NOTES_LIST = re.compile(r"\b(?:che|quali|quante|elenc\w*|mostr\w*|vedere|lista|mie)\b.*\b(?:note|promemoria)\b"
                         r"|\b(?:note|promemoria)\b.*\b(?:elenc\w*|lista)\b", re.IGNORECASE)
# azioni sulle note (anche «ricordami/annota/segnami», che aggiungono): l'indicazione dell'elenco sarebbe sbagliata
_NOTES_ACTION = re.compile(r"aggiung|\bcrea|salva|elimin|cancell|ricord|\bannot|\bsegn", re.IGNORECASE)


def tool_hints(text: str) -> str:
    """«fra 10 giorni», «100 giorni fa», «quanti giorni mancano all'Epifania»: indica al modello lo strumento e i
    dati da passare (sbagliava i conti a mente o la festività passata); il risultato lo dà lo strumento, visibile."""
    hints = []
    for match in _RELATIVE_DAYS.finditer(text):
        if match.group(1):
            hints.append(f"per «fra {match.group(1)} giorni» chiama `add_days` con days={match.group(1)}")
        else:
            hints.append(f"per «{match.group(2)} giorni fa» chiama `add_days` con days=-{match.group(2)}")
    if _HOLIDAY_QUESTION.search(text):
        words = f" {normalize_name(text)} "
        for key, name in holiday_names().items():
            if not key[0].isdigit() and f" {key} " in words.replace("'", " ' ").replace("?", " "):
                hints.append(f'per i giorni che mancano chiama `find_holiday` con name="{name}" senza anno '
                             "(conta la prossima)")
                break
    if _NOTES_LIST.search(text) and not _NOTES_ACTION.search(text):
        hints.append("per l'elenco delle note chiama `list_notes`")
    return f"{text} (indicazione del programma: {'; '.join(hints)})" if hints else text


def with_explained_question(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Copia per la chiamata al modello: solo le domande dell'utente, la cronologia resta com'era."""
    return [m.model_copy(update={"content": tool_hints(explain_multiplication(m.content))})
            if isinstance(m, HumanMessage) and isinstance(m.content, str) else m for m in messages]


def with_today(messages: list[AnyMessage], line: str) -> list[AnyMessage]:
    """Copia della lista con la data di oggi nel prompt di sistema, solo per la chiamata al modello."""
    if not line:
        return messages
    result = list(messages)
    for i, message in enumerate(result):
        if isinstance(message, SystemMessage):
            result[i] = message.model_copy(update={"content": f"{message.content}\n\n{line}"})
            break
    return result


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
                router: Callable[[list[AnyMessage], str], Route] | None = None,
                reviewer: Callable[[str, str, str, str, str], Review] | None = None, max_reviews: int = 3,
                summarizer: Callable[[str, str], str] | None = None, summary_threshold: int = 4000,
                summary_keep_turns: int = 2,
                confirmation_check: Callable[[list[dict], dict[int, bool]], list[dict]] | None = None,
                today: Callable[[], str] | None = None):
    model_with_tools = model.bind_tools(tools)
    # Gli errori dello strumento tornano al modello come ToolMessage con stato "error".
    # Niente wrap_tool_call: con un wrapper il ToolNode convertirebbe in messaggio anche gli errori di collegamento
    tool_node = ToolNode(tools, handle_tool_errors=tool_error_message)

    def model_node(state: State) -> dict:
        steps = state["steps"] + 1
        logger.debug("[grafo] nodo model: passaggio %d/%d", steps, max_steps)
        line = today() if today else ""
        messages = with_today(with_explained_question(state["messages"]), line)
        response = model_with_tools.invoke(with_summary(messages, state.get("summary", "")))
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
            target = "confirm" if confirmation_check else "tools"
        else:
            target = "step_limit"
        logger.debug("[grafo] instradamento dopo model: %s (steps=%d/%d)", target, state["steps"], max_steps)
        return target

    def tools_node(state: State, config: RunnableConfig) -> dict:
        configurable = {**config.get("configurable", {}), "note_decisions": state.get("decisions", {})}
        result = tool_node.invoke(state, {**config, "configurable": configurable})
        log_tool_calls(state["messages"][-1].tool_calls, result["messages"])
        return result

    def confirm_node(state: State) -> dict:
        needed = confirmation_check(state["messages"][-1].tool_calls, state.get("decisions", {}))
        if needed:
            logger.info("[grafo] turno sospeso: %d conferme richieste", len(needed))
        return {"confirmations": needed}

    def route_after_confirm(state: State) -> str:
        return END if state["confirmations"] else "tools"

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
        index = last_question_index(messages)
        # Turni precedenti con la regola del router: solo testo, ultimi messaggi
        recent = transcript(router_context(messages[:index]))
        # Risultati degli strumenti del turno, anche dei tentativi precedenti
        tool_results = "\n".join(f"{m.name}: {m.content}" for m in messages[index + 1:] if isinstance(m, ToolMessage))
        try:
            result = reviewer(messages[index].content, messages[-1].content, state.get("summary", ""), recent,
                              tool_results)
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
            result = router(state["messages"], state.get("summary", ""))
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

    def summarizer_node(state: State) -> dict:
        messages = state["messages"]
        summary = state.get("summary", "")
        before = estimate_tokens(messages, summary)
        if before <= summary_threshold:
            return {}
        cut = summary_cut(messages, summary_keep_turns)
        if cut == 0:
            return {}
        first = 1 if isinstance(messages[0], SystemMessage) else 0
        try:
            new_summary = summarizer(summary, transcript(messages[first:cut])).strip()
        except openai.APIError as error:
            logger.warning("[riassunto] non riuscito (%s): cronologia invariata", error)
            return {}
        if not new_summary:
            logger.warning("[riassunto] non riuscito (testo vuoto): cronologia invariata")
            return {}
        kept = messages[:first] + messages[cut:]
        line = summary_line(len(messages), len(kept), before, estimate_tokens(kept, new_summary))
        logger.debug(line)
        return {"messages": [RemoveMessage(id=m.id) for m in messages[first:cut]], "summary": new_summary,
                "summary_line": line}

    graph = StateGraph(State)
    graph.add_node("model", model_node)
    graph.add_node("tools", tools_node)
    graph.add_node("step_limit", step_limit_node)
    entry = "router" if router else "model"
    first = "summarizer" if summarizer else entry
    if confirmation_check:
        graph.add_node("confirm", confirm_node)
        graph.add_conditional_edges("confirm", route_after_confirm, ["tools", END])

        # Ripresa di un turno sospeso: si torna alla conferma, senza riassunto né router
        def route_from_start(state: State) -> str:
            last = state["messages"][-1]
            return "confirm" if isinstance(last, AIMessage) and last.tool_calls else first

        graph.add_conditional_edges(START, route_from_start, ["confirm", first])
    else:
        graph.add_edge(START, first)
    if summarizer:
        graph.add_node("summarizer", summarizer_node)
        graph.add_edge("summarizer", entry)
    if router:
        graph.add_node("router", router_node)
        graph.add_node("refusal", refusal_node)
        graph.add_conditional_edges("router", route_after_router, ["model", "refusal"])
        graph.add_edge("refusal", END)
    destinations = ["confirm" if confirmation_check else "tools", "step_limit", END]
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
