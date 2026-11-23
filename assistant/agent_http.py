"""Client HTTP leggero del servizio agente (SSE compreso): solo libreria standard e httpx."""

import json
from collections.abc import Iterable, Iterator

import httpx

UNAVAILABLE = "L'agente non risponde: esci e riavvia l'assistente."


class AgentUnavailable(Exception):
    """Servizio agente non raggiungibile o non avviabile."""


class AgentRequestError(Exception):
    """Errore restituito dal servizio agente: codice e messaggio in italiano."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status  # codice HTTP della risposta; None se l'errore è arrivato come evento SSE


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """Eventi `event:`/`data:` chiusi da una riga vuota; l'ultimo vale anche senza la riga vuota finale."""
    name, data = None, []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if name is not None:
                yield name, json.loads("\n".join(data))
            name, data = None, []
        elif line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            value = line[len("data:"):]
            data.append(value[1:] if value.startswith(" ") else value)
    if name is not None:
        yield name, json.loads("\n".join(data))


def _sse_lines(chunks: Iterable[str]) -> Iterator[str]:
    """Righe divise solo su a capo: iter_lines di httpx spezza anche su U+2028, U+0085 ecc., che nel JSON sono testo."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line.removesuffix("\r")
    if buffer:
        yield buffer


def error_from(response: httpx.Response) -> AgentRequestError:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "codice" in body:
        return AgentRequestError(body["codice"], body.get("messaggio", ""), response.status_code)
    return AgentRequestError("richiesta_non_valida", f"Richiesta rifiutata dall'agente (HTTP {response.status_code}).",
                             response.status_code)


class AgentHTTPClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        # Lettura senza limite: un turno con router, modello e revisore può durare minuti senza inviare byte
        self._http = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, read=None), transport=transport)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            return self._http.request(method, url, **kw)
        except httpx.TransportError as error:
            raise AgentUnavailable(UNAVAILABLE) from error

    def status(self) -> dict:
        response = self._request("GET", "/stato")
        if response.status_code not in (200, 503):
            raise error_from(response)
        return response.json()

    def turn(self, payload: dict) -> dict:
        response = self._request("POST", "/chat", json=payload)
        if response.status_code != 200:
            raise error_from(response)
        return response.json()

    def stream_turn(self, payload: dict) -> Iterator[tuple[str, dict]]:
        try:
            with self._http.stream("POST", "/chat/stream", json=payload) as response:
                if response.status_code != 200:
                    response.read()
                    raise error_from(response)
                yield from parse_sse(_sse_lines(response.iter_text()))
        except httpx.TransportError as error:
            raise AgentUnavailable(UNAVAILABLE) from error

    def close(self) -> None:
        self._http.close()

