import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assistant.config import load_settings
from langchain_core.messages import AIMessageChunk

from assistant.llm import (REASONING_KEY, LMStudioUnavailable, ModelNotFound, ReasoningChatOpenAI, build_chat_model,
                           check_model, list_models)

MODELS = {"data": [{"id": "google/gemma-4-e2b"}, {"id": "altro"}]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "/v1/models":
            body = json.dumps(MODELS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def settings(base_url, model):
    return load_settings({"LMSTUDIO_BASE_URL": base_url, "LMSTUDIO_MODEL": model})


def test_list_models(server):
    assert list_models(f"{server}/v1", 5) == ["google/gemma-4-e2b", "altro"]


def test_trailing_slash(server):
    assert list_models(f"{server}/v1/", 5) == ["google/gemma-4-e2b", "altro"]


def test_unreachable():
    with pytest.raises(LMStudioUnavailable, match="127.0.0.1:9"):
        list_models("http://127.0.0.1:9/v1", 2)


def test_model_missing(server):
    with pytest.raises(ModelNotFound) as e:
        check_model(settings(f"{server}/v1", "inventato"))
    assert e.value.available == ["google/gemma-4-e2b", "altro"]
    assert "altro" in str(e.value)


def test_model_present(server):
    check_model(settings(f"{server}/v1", "google/gemma-4-e2b"))


def test_build_chat_model():
    m = build_chat_model(settings("http://h:1234/v1", "google/gemma-4-e2b"))
    assert (m.model_name, m.max_retries, m.temperature) == ("google/gemma-4-e2b", 0, 0.2)


def make_reasoning_model():
    return ReasoningChatOpenAI(base_url="http://localhost:1/v1", model="m", api_key="x")


def make_chunk(delta):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": None}], "id": "x", "model": "m",
            "object": "chat.completion.chunk", "created": 0}


def test_reasoning_kept_in_stream_chunk():
    model = make_reasoning_model()
    result = model._convert_chunk_to_generation_chunk(
        make_chunk({"role": "assistant", "reasoning_content": "Thinking"}), AIMessageChunk, None)
    assert result.message.additional_kwargs[REASONING_KEY] == "Thinking"
    result = model._convert_chunk_to_generation_chunk(make_chunk({"content": "Ciao"}), AIMessageChunk, None)
    assert REASONING_KEY not in result.message.additional_kwargs and result.message.content == "Ciao"
    empty = {"choices": [], "id": "x", "model": "m", "object": "chat.completion.chunk", "created": 0}
    model._convert_chunk_to_generation_chunk(empty, AIMessageChunk, None)


def test_build_chat_model_keeps_reasoning():
    assert isinstance(build_chat_model(settings("http://h:1234/v1", "m")), ReasoningChatOpenAI)
