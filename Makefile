.PHONY: run run-frontend run-docker-worker check security-audit smoke-test frontend-smoke-test build-worker install-deps clean

HOST ?= 127.0.0.1
PORT ?= 8000
FRONTEND_HOST ?= 127.0.0.1
FRONTEND_PORT ?= 4762
WORKER_IMAGE ?= file-trans-convert-worker:latest

run:
	HOST=$(HOST) PORT=$(PORT) python3 server.py

run-frontend:
	FRONTEND_HOST=$(FRONTEND_HOST) FRONTEND_PORT=$(FRONTEND_PORT) python3 scripts/frontend-server.py

run-docker-worker:
	FILE_TRANS_USE_DOCKER=1 FILE_TRANS_WORKER_IMAGE=$(WORKER_IMAGE) HOST=$(HOST) PORT=$(PORT) python3 server.py

check:
	python3 -m py_compile server.py
	python3 -m py_compile scripts/frontend-server.py
	bash -n scripts/install-ubuntu-deps.sh scripts/smoke-test.sh scripts/frontend-smoke-test.sh
	python3 -m unittest discover -s tests
	python3 scripts/security-audit.py

security-audit:
	python3 scripts/security-audit.py

smoke-test:
	bash scripts/smoke-test.sh
	bash scripts/frontend-smoke-test.sh

frontend-smoke-test:
	bash scripts/frontend-smoke-test.sh

build-worker:
	docker build -f docker/convert-worker.Dockerfile -t $(WORKER_IMAGE) .

install-deps:
	bash scripts/install-ubuntu-deps.sh

clean:
	rm -rf data build
