FROM python:3.12-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r tickerflow && useradd -r -g tickerflow -d /app -s /sbin/nologin tickerflow

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput || true

RUN chown -R tickerflow:tickerflow /app
USER tickerflow

EXPOSE 8000

CMD ["gunicorn", "tickerflow.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
