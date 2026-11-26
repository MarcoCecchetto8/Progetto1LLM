# Agente (grafo LangGraph, server MCP in stdio e servizio delle note avviati nel container).
# Contesto di build: la radice del progetto (vedi compose.yaml).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistant/ ./assistant/
COPY lab_server/ ./lab_server/
COPY notes_service/ ./notes_service/
COPY agent_service/ ./agent_service/
COPY config/ ./config/

RUN useradd --create-home appuser
USER appuser

CMD ["python", "-m", "agent_service", "--host", "0.0.0.0"]
