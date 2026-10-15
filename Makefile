# Convenience targets (on Windows run the commands directly, or use `docker`).
PY ?= python

.PHONY: test lint pipeline reproduce reproduce-quick docker-build docker-test

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m pyflakes sdv experiments tests/test_sdv_*.py config.py llm_client.py

pipeline:
	$(PY) -m sdv --blue enumerate --n 40 --out outputs/pipeline_run

reproduce:
	$(PY) experiments/reproduce_all.py

reproduce-quick:
	$(PY) experiments/reproduce_all.py --quick

docker-build:
	docker build -t sdv-safety .

docker-test: docker-build
	docker run --rm sdv-safety
