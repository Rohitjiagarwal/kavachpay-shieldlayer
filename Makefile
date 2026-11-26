# KavachPay: one-command tasks. Works on Linux/macOS and on Windows via Git
# Bash. Python commands use the project venv if present.

PY ?= python
VENV := .venv
ifneq (,$(wildcard $(VENV)/bin/python))
  PY := $(VENV)/bin/python
endif
ifneq (,$(wildcard $(VENV)/Scripts/python.exe))
  PY := $(VENV)/Scripts/python.exe
endif

.PHONY: help venv install api web up down attack eval test lint typecheck audit demos export clean

help:
	@echo "KavachPay tasks:"
	@echo "  make venv        create the Python venv"
	@echo "  make install     install Python deps (core + dev + app)"
	@echo "  make api         run the API on :8080 (reload)"
	@echo "  make web         run the dashboard on :3000"
	@echo "  make up          docker compose up --build (API + dashboard on :7860)"
	@echo "  make test        run the Python test suite (offline, no API keys used)"
	@echo "  make attack      replay the attack library and print the scorecard"
	@echo "  make demos       re-record the 8 mission replays (local Ollama + heuristic L2)"
	@echo "  make export      build the static dashboard into dashboard/out"
	@echo "  make lint        ruff"

venv:
	uv venv $(VENV)

install:
	uv pip install -e ".[dev,app]"

api:
	$(PY) -m uvicorn app.main:app --port 8080 --reload

web:
	cd dashboard && pnpm dev

up:
	docker compose up --build

down:
	docker compose down

attack:
	$(PY) -m attacks.run_attacks

attack-baseline:
	$(PY) -m attacks.run_attacks --baseline

eval:
	$(PY) eval/run_eval.py --gate

demos:
	$(PY) scripts/record_demos.py

export:
	cd dashboard && STATIC_EXPORT=1 NEXT_PUBLIC_SAME_ORIGIN=1 pnpm build

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

typecheck:
	$(PY) -m mypy shared shield app || true

audit:
	$(PY) -m pip_audit || true

clean:
	rm -rf app/data/*.db app/data/uploads/* dashboard/out
