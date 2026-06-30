.PHONY: run check build-tools install-deps clean

HOST ?= 127.0.0.1
PORT ?= 8000

run:
	HOST=$(HOST) PORT=$(PORT) python3 server.py

check:
	python3 -m py_compile server.py

build-tools:
	bash scripts/build-toolchain.sh

install-deps:
	bash scripts/install-ubuntu-deps.sh

clean:
	rm -rf data build
