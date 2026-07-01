FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir .

ENV PORT=8080
ENV DATA_DIR=/app/data
ENV WORK_DIR=/app/work

EXPOSE 8080

CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-2} --timeout ${GUNICORN_TIMEOUT_SECONDS:-21600}"]
