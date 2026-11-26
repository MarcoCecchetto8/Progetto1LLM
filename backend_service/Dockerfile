# Back-end delle chat. Contesto di build: la radice del progetto (vedi compose.yaml).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-backend.txt .
RUN pip install --no-cache-dir -r requirements-backend.txt

# Dell'assistente serve solo il client HTTP leggero dell'agente
COPY assistant/__init__.py assistant/agent_http.py ./assistant/
COPY backend_service/ ./backend_service/

RUN useradd --create-home appuser
USER appuser

CMD ["python", "-m", "backend_service", "--host", "0.0.0.0"]
