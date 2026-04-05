# /test

Standard test commands. Run these to verify your work at any point.

```bash
# Run all tests
uv run pytest

# With coverage
uv run pytest --cov=src --cov-report=term-missing

# Single file
uv run pytest tests/test_claude_matcher.py -v

# Pattern match
uv run pytest -k "test_returns_none" -v

# No output capture
uv run pytest -s -v

# HTML coverage report
uv run pytest --cov=src --cov-report=html
open htmlcov/index.html

# Dry run end-to-end (no real API calls)
DRY_RUN=true uv run python -m job_scout.orchestrator

# Install / sync dependencies
uv sync --extra dev

# Install Playwright (first time only)
uv run playwright install chromium --with-deps
```
