FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY deploy/requirements-agent.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 agent
COPY hotel/__init__.py hotel/voice_worker.py hotel/voice_turns.py hotel/voice_input.py hotel/voice_health.py hotel/worker_auth.py hotel/privacy_logging.py /app/hotel/
USER agent
CMD ["python", "-m", "hotel.voice_worker", "start"]
