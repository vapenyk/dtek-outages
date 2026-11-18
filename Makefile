PYTHON ?= python3

.PHONY: help install dev test clean

help:
	@echo "make install  - install for the current user (pip install --user .)"
	@echo "make dev      - editable install (pip install -e .)"
	@echo "make test     - run the unit tests"
	@echo "make clean    - remove build artefacts"
	@echo
	@echo "Run without installing: ./dtek-outages"

install:
	$(PYTHON) -m pip install --user .

dev:
	$(PYTHON) -m pip install -e .

test:
	$(PYTHON) -m unittest discover -s tests -t .

clean:
	rm -rf build dist *.egg-info
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
