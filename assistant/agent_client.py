"""Client HTTP del servizio agente (SSE compreso) e avvio automatico del servizio in locale."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping

import httpx

from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptArgument, PromptInfo

UNAVAILABLE = "L'agente non risponde: esci e riavvia l'assistente."
REFUSED_PREFIX = "Il server ha rifiutato il prompt: "
START_TIMEOUT = 60.0
STOP_TIMEOUT = 10.0
API_ROLES = {"utente": "user", "assistente": "assistant"}


class AgentUnavailable(Exception):
    """Servizio agente non raggiungibile o non avviabile."""


class AgentRequestError(Exception):
    """Errore restituito dal servizio agente: codice e messaggio in italiano."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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


def _error_from(response: httpx.Response) -> AgentRequestError:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "codice" in body:
        return AgentRequestError(body["codice"], body.get("messaggio", ""))
    return AgentRequestError("richiesta_non_valida", f"Richiesta rifiutata dall'agente (HTTP {response.status_code}).")


class AgentClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        # Lettura senza limite: un turno con router, modello e revisore può durare minuti senza inviare byte
        self._http = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, read=None), transport=transport)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            return self._http.request(method, url, **kw)
        except httpx.TransportError as error:
            raise AgentUnavailable(UNAVAILABLE) from error

    def _prompt_error(self, response: httpx.Response) -> Exception:
        error = _error_from(response)
        if error.code == "prompt_rifiutato":
            return MCPPromptError(error.message.removeprefix(REFUSED_PREFIX))
        if error.code == "strumenti_non_raggiungibili":
            return MCPConnectionError(error.message)
        return error

    def status(self) -> dict:
        response = self._request("GET", "/stato")
        if response.status_code not in (200, 503):
            raise _error_from(response)
        return response.json()

    def prompts(self) -> list[PromptInfo]:
        response = self._request("GET", "/prompts")
        if response.status_code != 200:
            raise self._prompt_error(response)
        return [PromptInfo(p["nome"], p["descrizione"],
                           tuple(PromptArgument(a["nome"], a["descrizione"], a["obbligatorio"])
                                 for a in p["argomenti"]))
                for p in response.json()]

    def get_prompt(self, name: str, arguments: dict[str, str]) -> list[tuple[str, str]]:
        response = self._request("POST", f"/prompts/{name}", json={"argomenti": arguments})
        if response.status_code != 200:
            raise self._prompt_error(response)
        return [(API_ROLES.get(m["ruolo"], "user"), m["contenuto"]) for m in response.json()["messaggi"]]

    def stream_turn(self, payload: dict) -> Iterator[tuple[str, dict]]:
        try:
            with self._http.stream("POST", "/chat/stream", json=payload) as response:
                if response.status_code != 200:
                    response.read()
                    raise _error_from(response)
                yield from parse_sse(_sse_lines(response.iter_text()))
        except httpx.TransportError as error:
            raise AgentUnavailable(UNAVAILABLE) from error

    def close(self) -> None:
        self._http.close()


def _port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _responds(url: str) -> bool:
    # Qualsiasi codice vale: 503 significa solo che il modello è spento
    try:
        httpx.get(f"{url}/stato", timeout=10.0)
    except httpx.TransportError:
        return False
    return True


class LocalAgentService:
    """Avvia il servizio agente come sottoprocesso locale."""

    def __init__(self, port: int = 8001, quiet: bool = True, env: Mapping[str, str] | None = None):
        self.port = port
        self.quiet = quiet
        self.env = env
        self._proc: subprocess.Popen | None = None
        self._stderr = None

    def start(self) -> str:
        url = f"http://127.0.0.1:{self.port}"
        if _port_in_use(self.port):
            raise AgentUnavailable(
                f"La porta {self.port} è già in uso (forse l'agente di Docker è acceso: docker compose down)."
            )
        command = [sys.executable, "-m", "agent_service", "--port", str(self.port)]
        options: dict = {}
        if self.quiet:
            command.append("--quiet")
            # Un file e non una pipe: a pipe piena il figlio si bloccherebbe
            self._stderr = tempfile.TemporaryFile()
            options = {"stdout": subprocess.DEVNULL, "stderr": self._stderr}
        # Su Windows Ctrl+C arriva a tutti i processi della console: senza gruppo separato l'agente
        # morirebbe quando Ctrl+C ferma solo il turno.
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        if self.env is not None:
            options["env"] = dict(self.env)
        proc = self._proc = subprocess.Popen(command, **options)
        deadline = time.monotonic() + START_TIMEOUT
        while True:
            if proc.poll() is not None:
                details = self._last_stderr_lines()
                self.close()
                raise AgentUnavailable("L'agente non è partito" + (f": {details}" if details else "."))
            if _responds(url):
                return url
            if time.monotonic() >= deadline:
                self.close()
                raise AgentUnavailable(f"L'agente non è partito entro {START_TIMEOUT:g} secondi.")
            time.sleep(0.2)

    def _last_stderr_lines(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.seek(0)
        lines = [line for line in self._stderr.read().decode("utf-8", "replace").splitlines() if line.strip()]
        return "\n".join(lines[-5:])

    def close(self) -> None:
        proc, self._proc = self._proc, None
        try:
            if proc is not None and proc.poll() is None:
                # Chiusura ordinata: l'agente deve eseguire il suo finally (servizio note e server MCP)
                try:
                    if os.name == "nt":
                        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                    else:
                        proc.terminate()
                except OSError:
                    proc.terminate()
                try:
                    proc.wait(timeout=STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        finally:
            stderr, self._stderr = self._stderr, None
            if stderr is not None:
                stderr.close()
