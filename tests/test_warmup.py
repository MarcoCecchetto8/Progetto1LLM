from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.warmup import WARMUP_TEXT, warm_up


class RecordingModel:
    """Modello finto: registra strumenti, messaggi e argomenti della chiamata."""

    def __init__(self, fail: bool = False):
        self.tools = None
        self.calls = []
        self.fail = fail

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages, **kwargs):
        if self.fail:
            raise ConnectionError("LM Studio spento")
        self.calls.append((messages, kwargs))


def test_warm_up_sends_the_agent_prompt_prefix_with_one_token():
    model, routed = RecordingModel(), []
    warm_up(model, ["strumento"], "Sei l'assistente.", lambda: "Oggi è giovedì.",
            router=lambda messages, summary: routed.append((messages, summary)))
    assert model.tools == ["strumento"]
    messages, kwargs = model.calls[0]
    # Stesso inizio delle chiamate vere: prompt di sistema con la riga della data, poi la domanda
    assert messages[0] == SystemMessage("Sei l'assistente.\n\nOggi è giovedì.")
    assert messages[1] == HumanMessage(WARMUP_TEXT)
    assert kwargs == {"max_tokens": 1}
    assert routed == [([HumanMessage(WARMUP_TEXT)], "")]


def test_warm_up_never_raises(caplog):
    # LM Studio spento o lento: il riscaldamento si limita a un avviso, l'agente resta utilizzabile
    warm_up(RecordingModel(fail=True), [], "Sei l'assistente.", lambda: "", router=None)
    assert "[riscaldamento]" in caplog.text
