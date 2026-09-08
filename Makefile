# Development artifacts remain local to the working project.
export UV_CACHE_DIR := $(CURDIR)/.local_read_mcp/uv-cache
export UV_PROJECT_ENVIRONMENT := $(CURDIR)/.local_read_mcp/dev-runtime
export PYTHONDONTWRITEBYTECODE := 1
export TMPDIR := $(CURDIR)/.local_read_mcp/tmp

.PHONY: help test coverage lint skill
help:
	@echo "make test | make coverage | make lint | make skill"

test:
	mkdir -p "$(TMPDIR)"
	uv run --locked --group dev pytest --basetemp=.local_read_mcp/pytest-tmp

coverage:
	mkdir -p "$(TMPDIR)" .local_read_mcp/coverage
	uv run --locked --group dev pytest --basetemp=.local_read_mcp/pytest-tmp --cov --cov-report=term-missing --cov-report=html

lint:
	uv run --locked --group dev ruff check src/ scripts/

skill:
	python3 scripts/package_skill.py
