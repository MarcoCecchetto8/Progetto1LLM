"""Client HTTP del servizio agente per la CLI (prompt compresi) e avvio automatico del servizio in locale."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping

import httpx

from assistant.agent_http import (UNAVAILABLE, AgentHTTPClient, AgentRequestError, AgentUnavailable,  # noqa: F401
                                  error_from, parse_sse)  # noqa: F401
from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptArgument, PromptInfo

REFUSED_PREFIX = "Il server ha rifiutato il prompt: "
START_TIMEOUT = 60.0
STOP_TIMEOUT = 10.0
API_ROLES = {"utente": "user", "assistente": "assistant"}


class AgentClient(AgentHTTPClient):
    def _prompt_error(self, response: httpx.Response) -> Exception:
        error = error_from(response)
        if error.code == "prompt_rifiutato":
            return MCPPromptError(error.message.removeprefix(REFUSED_PREFIX))
        if error.code == "strumenti_non_raggiungibili":
            return MCPConnectionError(error.message)
        return error

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


def wait_until_responds(url: str, timeout: float | None = None, alive=lambda: True) -> bool:
    """Attende che /stato risponda (con qualsiasi codice); False se scade il tempo o `alive` diventa falso."""
    deadline = time.monotonic() + (START_TIMEOUT if timeout is None else timeout)
    while alive():
        if _responds(url):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)
    return False


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
        if wait_until_responds(url, alive=lambda: proc.poll() is None):
            return url
        if proc.poll() is not None:
            details = self._last_stderr_lines()
            self.close()
            raise AgentUnavailable("L'agente non è partito" + (f": {details}" if details else "."))
        self.close()
        raise AgentUnavailable(f"L'agente non è partito entro {START_TIMEOUT:g} secondi.")

    def startup_warnings(self) -> list[str]:
        """Righe di avviso già scritte dall'agente (in modalità silenziosa il suo stderr non arriva al terminale)."""
        if self._stderr is None:
            return []
        self._stderr.seek(0)
        return [line for line in self._stderr.read().decode("utf-8", "replace").splitlines() if line.strip()]

    def _last_stderr_lines(self) -> str:
        if self._stderr is None:
            return ""
        return "\n".join(self.startup_warnings()[-5:])

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
