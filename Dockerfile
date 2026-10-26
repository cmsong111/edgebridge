FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY edgebridge.py .

# Run as an unprivileged user; registrations (and the optional log file) live in /app/data
RUN useradd --system edgebridge \
    && mkdir data \
    && chown edgebridge:edgebridge data
USER edgebridge
WORKDIR /app/data

EXPOSE 8088
CMD ["python", "/app/edgebridge.py"]
