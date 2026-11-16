"""Vista del turno: scrive ragionamento, strumenti e risposta mentre arrivano dal grafo."""

import json
from typing import Callable

from langchain_core.messages import AIMessageChunk

from assistant.llm import REASONING_KEY
from assistant.reviewer import review_line

REASONING_HEADER = "[ragionamento]"
ANSWER_HEADER = "[risposta]"
INTERRUPTED = "Risposta interrotta."
THINKING = "…sto pensando"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


class TurnView:
    def __init__(self, write: Callable[[str], None], color: bool, show_reasoning: bool):
        self._write = write
        self._color = color
        self._show_reasoning = show_reasoning
        self._section: str | None = None
        self._at_line_start = True

    def _emit(self, text: str) -> None:
        if text:
            self._write(text)
            self._at_line_start = text.endswith("\n")

    def _newline_if_needed(self) -> None:
        if not self._at_line_start:
            self._emit("\n")

    def _dim(self, text: str) -> str:
        return f"{DIM}{text}{RESET}" if self._color else text

    def reasoning(self, text: str) -> None:
        if not self._show_reasoning:
            return
        if self._section != "reasoning":
            self._newline_if_needed()
            self._section = "reasoning"
            self._emit(self._dim(REASONING_HEADER + "\n"))
        # Il colore non cambia l'ultimo carattere visibile: l'a capo si controlla sul testo.
        self._write(self._dim(text))
        self._at_line_start = text.endswith("\n") if text else self._at_line_start

    def answer(self, text: str) -> None:
        if self._section != "answer":
            self._newline_if_needed()
            # Senza il grigio la risposta non si distinguerebbe dal ragionamento appena sopra
            if self._section == "reasoning" and not self._color:
                self._emit(ANSWER_HEADER + "\n")
            self._section = "answer"
        self._emit(text)

    def _line(self, text: str) -> None:
        self._newline_if_needed()
        self._emit(text + "\n")
        self._section = None

    def tool_call(self, name: str, args: dict) -> None:
        self._line(f"[strumento] {name} {json.dumps(args, ensure_ascii=False)}")

    def tool_result(self, name: str, content: str, error: bool) -> None:
        label = f"{name} errore" if error else name
        self._line(f"[strumento] {label} → {content}")

    def extra(self, text: str) -> None:
        self._line(text)

    def finish(self) -> None:
        self._newline_if_needed()


def _last_message(update) -> object | None:
    messages = (update or {}).get("messages") or []
    return messages[-1] if messages else None


def stream_turn(graph, state: dict, view: TurnView, config: dict | None = None) -> dict:
    final: dict = {}
    shown = ""          # testo di risposta già mostrato
    got_chunks = False  # in questo passaggio del modello sono arrivati pezzi di risposta
    try:
        for mode, payload in graph.stream(state, config, stream_mode=["messages", "updates", "values"]):
            if mode == "values":
                final = payload
            elif mode == "messages":
                chunk, meta = payload
                if not isinstance(chunk, AIMessageChunk) or meta.get("langgraph_node") != "model":
                    continue
                reasoning = chunk.additional_kwargs.get(REASONING_KEY)
                if isinstance(reasoning, str) and reasoning:
                    view.reasoning(reasoning)
                if isinstance(chunk.content, str) and chunk.content:
                    view.answer(chunk.content)
                    got_chunks = True
            elif mode == "updates":
                for node, update in payload.items():
                    if node == "reviewer":
                        view.extra(review_line(update["review_outcome"], update["review_reason"], update["reviews"]))
                        continue
                    message = _last_message(update)
                    if message is None:
                        continue
                    if node == "model":
                        content = message.content
                        if not got_chunks and isinstance(content, str) and content:
                            view.answer(content)
                        for call in message.tool_calls:
                            view.tool_call(call["name"], call["args"])
                        shown = content if isinstance(content, str) else ""
                        got_chunks = False
                    elif node == "tools":
                        for m in update["messages"]:
                            view.tool_result(m.name, m.content, m.status == "error")
                    elif node == "answer_check":
                        content = message.content
                        if shown and content.startswith(shown):
                            view.extra(content[len(shown):].lstrip("\n"))
                        else:
                            view.extra(content)
                    elif node in ("step_limit", "refusal"):
                        view.extra(message.content)
    finally:
        view.finish()
    return final
