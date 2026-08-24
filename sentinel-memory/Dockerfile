FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 8091
CMD ["uvicorn", "bdlh_memory.main:app", "--host", "0.0.0.0", "--port", "8091"]
