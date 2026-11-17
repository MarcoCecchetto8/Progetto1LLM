from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from assistant.reviewer import (FEEDBACK, REVIEW_SUMMARY_HEADER, REVIEWER_INSTRUCTIONS, Review, build_reviewer,
                                feedback_message, is_review_feedback, last_question_index, review_line,
                                review_request)
from assistant.summarizer import SUMMARY_HEADER


class FakeStructured:
    def __init__(self, owner):
        self.owner = owner

    def invoke(self, messages):
        self.owner.invoked = messages
        return Review(coerente=False, motivo="manca la seconda parte.")


class FakeModel:
    def model_copy(self, update):
        self.update = update
        return self

    def with_structured_output(self, schema, method):
        self.schema = schema
        self.method = method
        return FakeStructured(self)


def test_review_request():
    assert review_request("D?", "R.") == "Domanda dell'utente:\nD?\n\nRisposta proposta:\nR."


def test_review_request_with_context():
    tail = "Domanda dell'utente:\nD?\n\nRisposta proposta:\nR."
    summary = "Riassunto della conversazione precedente:\nS\n\n"
    recent = "Conversazione recente:\nUtente: a\nAssistente: b\n\n"
    assert review_request("D?", "R.", "S") == summary + tail
    assert review_request("D?", "R.", "", "Utente: a\nAssistente: b") == recent + tail
    assert review_request("D?", "R.", "S", "Utente: a\nAssistente: b") == summary + recent + tail


def test_review_request_with_tool_results():
    tail = "Domanda dell'utente:\nD?\n\nRisposta proposta:\nR."
    tools = "Risultati degli strumenti in questo turno:\nlist_notes: 2 note\n\n"
    assert review_request("D?", "R.", "", "", "list_notes: 2 note") == tools + tail
    assert review_request("D?", "R.", "S", "Utente: a", "list_notes: 2 note") == (
        "Riassunto della conversazione precedente:\nS\n\nConversazione recente:\nUtente: a\n\n" + tools + tail)


def test_summary_header_matches_agent():
    # reviewer.py non può importare summarizer (import circolare): le due intestazioni devono coincidere
    assert REVIEW_SUMMARY_HEADER == SUMMARY_HEADER


def test_feedback_message_is_marked():
    msg = feedback_message("manca X.")
    assert isinstance(msg, HumanMessage)
    assert FEEDBACK.format(motivo="manca X.") in msg.content
    assert is_review_feedback(msg)
    assert not is_review_feedback(HumanMessage("normale"))


def test_last_question_index_skips_feedback():
    messages = [SystemMessage("s"), HumanMessage("q"), AIMessage("bozza"), feedback_message("m."), AIMessage("r")]
    assert last_question_index(messages) == 1


def test_last_question_index_without_human():
    assert last_question_index([SystemMessage("s"), AIMessage("a")]) == -1


def test_build_reviewer():
    model = FakeModel()
    result = build_reviewer(model)("domanda", "risposta")
    assert model.update == {"reasoning_effort": "none"}
    assert model.schema is Review
    assert model.method == "json_schema"
    assert model.invoked == [SystemMessage(REVIEWER_INSTRUCTIONS),
                             HumanMessage(review_request("domanda", "risposta"))]
    assert result == Review(coerente=False, motivo="manca la seconda parte.")


def test_build_reviewer_with_context():
    model = FakeModel()
    build_reviewer(model)("domanda", "risposta", "S", "Utente: a", "clock: 10:00")
    assert model.invoked[1] == HumanMessage(review_request("domanda", "risposta", "S", "Utente: a", "clock: 10:00"))


def test_review_lines():
    assert review_line("approved", "", 0) == "[revisore] coerente"
    assert review_line("retry", "manca X.", 1) == "[revisore] non coerente: manca X. → nuova risposta"
    assert review_line("limit", "manca X.", 2) == "[revisore] limite raggiunto (2 revisioni): resta l'ultima risposta"
    assert review_line("invalid", "", 0) == "[revisore] verdetto non valido: risposta approvata"


def test_instructions_accept_explained_impossibility():
    # Prova reale: senza questa frase il revisore bocciava 3 volte una conversione spiegata come impossibile
    assert "spiega perché una parte della domanda non si può soddisfare" in REVIEWER_INSTRUCTIONS
