FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN pip install --no-cache-dir "uv==0.12.3" \
    && uv sync --frozen --no-dev --extra postgres

EXPOSE 8090

CMD ["uvicorn", "stockwise_analysis.main:app", "--host", "0.0.0.0", "--port", "8090"]
