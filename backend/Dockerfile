FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY sql ./sql

# Roda como usuario nao-root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
# Sem access log no uvicorn: o nginx ja registra (e omite o link secreto do calendario).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
