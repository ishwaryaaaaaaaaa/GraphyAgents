FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LLM_MODE=off
# Without this, Python buffers its output when it is not attached to a terminal, so `docker compose up`
# would look frozen for minutes while the tests and evaluations are in fact running.
ENV PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "run_eval.py", "--set", "meera"]
