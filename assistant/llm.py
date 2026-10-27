"""Collegamento a LM Studio: elenco dei modelli, verifica e client di chat."""

import json
import urllib.error
import urllib.request

from langchain_openai import ChatOpenAI

from assistant.config import Settings


class LMStudioUnavailable(Exception):
    """LM Studio non raggiungibile o risposta non valida; il messaggio contiene l'URL provato."""


class ModelNotFound(Exception):
    """Il modello configurato non è fra quelli del server."""

    def __init__(self, model: str, available: list[str]):
        self.available = available
        elenco = ", ".join(available) if available else "(nessuno)"
        super().__init__(f"Modello '{model}' non trovato. Modelli disponibili: {elenco}.")


def list_models(base_url: str, timeout: float) -> list[str]:
    url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
        return [item["id"] for item in payload["data"]]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LMStudioUnavailable(f"LM Studio non raggiungibile o risposta non valida su {url}: {error}") from error


def check_model(settings: Settings) -> None:
    available = list_models(settings.base_url, settings.timeout)
    if settings.model not in available:
        raise ModelNotFound(settings.model, available)


def build_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.base_url,
        model=settings.model,
        api_key="lm-studio",
        timeout=settings.timeout,
        temperature=settings.temperature,
        max_retries=0,
    )
