PDF ?= data/reports/CITIGROUP.pdf

setup:
	poetry install

run:
	poetry run finxtractor run $(PDF)

eval:
	@echo "eval: not implemented yet (Phase 5)"

demo:
	@echo "demo: not implemented yet (Phase 7)"

.PHONY: setup run eval demo