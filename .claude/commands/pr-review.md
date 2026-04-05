# /pr-review

Run this checklist before opening any PR. Do not open the PR until all items pass.

## Commands to run first

```bash
# Full test suite with coverage
uv run pytest --cov=src --cov-report=term-missing

# Check for accidentally staged secrets
git diff --cached | grep -iE "(api_key|token|password|secret)" \
  && echo "WARNING: possible secret staged"

# Review staged diff
git diff --cached
```

## Checklist

**Code quality**
- [ ] Every new function has a complete type signature including return type
- [ ] No raw dicts passed between modules — dataclasses used throughout
- [ ] No `print()` statements — only `logging`
- [ ] No hardcoded secrets, tokens, or API keys
- [ ] No `TODO` or `FIXME` left in committed code
- [ ] `pathlib.Path` used everywhere — no `os.path`

**Testing**
- [ ] Every new function has at least one test
- [ ] Red → Yellow → Green followed — no implementation before its test
- [ ] No tests make real HTTP, Supabase, or Anthropic calls
- [ ] `pytest --cov` passes at ≥ 80%
- [ ] Coverage report pasted into PR body

**Configuration**
- [ ] `.env.example` updated if new env vars introduced
- [ ] No `.env` file staged

## PR body must include

1. One paragraph: what this phase builds and why
2. Bullet list of every file created or modified
3. Any manual validation performed (e.g. probe results, live test)
4. Full output of `uv run pytest --cov=src --cov-report=term-missing`
5. Known limitations or follow-up items
