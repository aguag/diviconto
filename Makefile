.PHONY: test test-v help

help:
	@echo "Target disponibili:"
	@echo "  make test     - lancia tutti i test"
	@echo "  make test-v   - test con output dettagliato"

test:
	python -m unittest discover -s tests

test-v:
	python -m unittest discover -s tests -v
