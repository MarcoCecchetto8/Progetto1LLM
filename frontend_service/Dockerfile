# Front-end web. Contesto di build: la radice del progetto (vedi compose.yaml).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-frontend.txt .
RUN pip install --no-cache-dir -r requirements-frontend.txt

COPY frontend_service/ ./frontend_service/

RUN useradd --create-home appuser
USER appuser

CMD ["python", "-m", "frontend_service", "--host", "0.0.0.0"]
