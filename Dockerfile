FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LLM_MODE=off
CMD ["python", "run_eval.py", "--set", "meera"]
