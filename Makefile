.PHONY: install test run frontend-install frontend-build docker-up docker-down health

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m unittest discover -s tests -v

run:
	$(PYTHON) -m uvicorn src.api:app --reload --port 8003

frontend-install:
	cd frontend && npm ci

frontend-build:
	cd frontend && npm run build

docker-up:
	docker compose up --build

docker-down:
	docker compose down

health:
	curl -f http://127.0.0.1:8003/health
