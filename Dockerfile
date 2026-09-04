FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install --retries 6 --timeout 180 -r requirements.txt

COPY . /app

EXPOSE 8000 8501

# Overridden per-service in docker-compose.yml; this is the default.
CMD ["python", "main.py"]
