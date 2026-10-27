FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistant/ ./assistant/

RUN useradd --create-home appuser
USER appuser

CMD ["python", "-m", "assistant"]
