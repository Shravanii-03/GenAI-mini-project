# Reproducible environment for the SDV timing-safety and threat-detection project.
#   docker build -t sdv-safety .
#   docker run --rm sdv-safety                                  # runs the test suite
#   docker run --rm sdv-safety python -m sdv --blue enumerate   # end-to-end pipeline, no API key
#   docker run --rm sdv-safety python experiments/reproduce_all.py --quick
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt pytest

COPY . .

# No API key is baked in. Pass one at run time only if you want live LLM calls:
#   docker run --rm -e GROQ_API_KEY=... sdv-safety python -m sdv --llm-model qwen/qwen3.8-27b
CMD ["python", "-m", "pytest", "tests", "-q"]
