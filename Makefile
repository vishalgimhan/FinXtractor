PDF ?= data/reports/CITIGROUP.pdf

setup:
	poetry install

run:
	poetry run finxtractor run $(PDF)

eval:
	@echo "eval: not implemented yet (Phase 5)"

dashboard:
	poetry run streamlit run src/finxtractor/dashboard.py

api:
	poetry run uvicorn api.main:app --reload

start:
	poetry run finxtractor start

demo: dashboard

.PHONY: setup run eval demo dashboard api start