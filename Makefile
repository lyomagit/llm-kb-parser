.PHONY: install test lint typecheck build clean doctor

install:
	pip install -e ".[dev,lint]"

test:
	pytest

lint:
	ruff check src/ tests/

typecheck:
	mypy src/kbparser/

build:
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

doctor:
	kbparser doctor
