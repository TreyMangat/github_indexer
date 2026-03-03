FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for git + building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src

RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "repo_recall.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
