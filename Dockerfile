FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.runtime.lock ./
RUN python -m pip install --no-cache-dir -r requirements.runtime.lock

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts/start_render.sh /app/start-render.sh
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 appuser \
    && chmod 755 /app/start-render.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "research_data_builder.main:app", "--host", "0.0.0.0", "--port", "8000"]

