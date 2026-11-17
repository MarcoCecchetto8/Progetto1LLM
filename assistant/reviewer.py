"""Revisore della risposta: giudica la coerenza con la domanda con un'uscita strutturata."""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

REVIEWER_INSTRUCTIONS = (
    "Sei il revisore dell'assistente del laboratorio. Ricevi la domanda dell'utente e la risposta proposta dall'assistente.\n"
    "Decidi se la risposta è coerente con la domanda: risponde a TUTTE le parti richieste e non devia dal tema.\n"
    "Non controllare se i numeri o i fatti sono giusti: controlla solo che ogni parte della domanda abbia una risposta.\n"
    "Se l'assistente spiega perché una parte della domanda non si può soddisfare "
    "(per esempio uno strumento non la supporta), quella parte ha una risposta.\n"
    "Un saluto o una frase di cortesia ricevono una risposta coerente se l'assistente risponde in modo cortese.\n"
    "Se non è coerente, il motivo dice in una frase breve in italiano che cosa manca o che cosa è fuori tema."
)

# Stesso testo di SUMMARY_HEADER (assistant.summarizer, che importa questo modulo): lo verifica un test
REVIEW_SUMMARY_HEADER = "Riassunto della conversazione precedente:"

FEEDBACK = (
    "[Revisore] La risposta non è completa o non è in tema: {motivo} "
    "Rispondi di nuovo alla domanda dell'utente, in modo completo, usando gli strumenti se servono."
)

_LINES = {
    "approved": "[revisore] coerente",
    "retry": "[revisore] non coerente: {motivo} → nuova risposta",
    "limit": "[revisore] limite raggiunto ({n} revisioni): resta l'ultima risposta",
    "invalid": "[revisore] verdetto non valido: risposta approvata",
}


class Review(BaseModel):
    coerente: bool = Field(description="True se la risposta copre tutte le parti della domanda e resta in tema.")
    motivo: str = Field(description="Frase breve in italiano: che cosa manca o che cosa è fuori tema.")


def review_request(question: str, answer: str, summary: str = "", recent: str = "", tools: str = "") -> str:
    # Riassunto e conversazione recente: senza, il revisore boccia le domande sulla conversazione stessa.
    # Risultati degli strumenti: senza, boccia i dati che non trova nel contesto (note, ora)
    context = ""
    if summary:
        context += f"{REVIEW_SUMMARY_HEADER}\n{summary}\n\n"
    if recent:
        context += f"Conversazione recente:\n{recent}\n\n"
    if tools:
        context += f"Risultati degli strumenti in questo turno:\n{tools}\n\n"
    return f"{context}Domanda dell'utente:\n{question}\n\nRisposta proposta:\n{answer}"


def build_reviewer(model: BaseChatModel) -> Callable[[str, str, str, str, str], Review]:
    # Senza ragionamento: il giudizio deve essere rapido
    structured = model.model_copy(update={"reasoning_effort": "none"}).with_structured_output(
        Review, method="json_schema"
    )

    def review(question: str, answer: str, summary: str = "", recent: str = "", tools: str = "") -> Review:
        request = review_request(question, answer, summary, recent, tools)
        return structured.invoke([SystemMessage(REVIEWER_INSTRUCTIONS), HumanMessage(request)])

    return review


def feedback_message(motivo: str) -> HumanMessage:
    return HumanMessage(FEEDBACK.format(motivo=motivo), additional_kwargs={"review_feedback": True})


def is_review_feedback(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get("review_feedback"))


def last_question_index(messages: list[AnyMessage]) -> int:
    """Indice dell'ultima domanda vera: le indicazioni del revisore non aprono un nuovo turno."""
    return max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not is_review_feedback(m)),
        default=-1,
    )


def review_line(outcome: str, motivo: str, reviews: int) -> str:
    return _LINES[outcome].format(motivo=motivo, n=reviews)
