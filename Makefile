.PHONY: run run-docker-worker check smoke-test build-tools build-worker install-deps clean

HOST ?= 127.0.0.1
PORT ?= 8000
WORKER_IMAGE ?= file-trans-convert-worker:latest

run:
	HOST=$(HOST) PORT=$(PORT) python3 server.py

run-docker-worker:
	FILE_TRANS_USE_DOCKER=1 FILE_TRANS_WORKER_IMAGE=$(WORKER_IMAGE) HOST=$(HOST) PORT=$(PORT) python3 server.py

check:
	python3 -m py_compile server.py
	python3 -m unittest discover -s tests

smoke-test:
	bash scripts/smoke-test.sh

build-tools:
	bash scripts/build-toolchain.sh

build-worker:
	docker build -f docker/convert-worker.Dockerfile -t $(WORKER_IMAGE) .

install-deps:
	bash scripts/install-ubuntu-deps.sh

clean:
	rm -rf data build
