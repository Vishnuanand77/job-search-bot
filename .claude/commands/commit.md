# /commit

Stage and commit changes following project conventions. Never `git add .` — always review what is being committed.

## Step 1 — Review the diff

```bash
git diff
git diff --cached
git status
```

Read the full diff. Understand every change before writing the message.

## Step 2 — Check for problems

Abort and fix if any of the following are present:

- Secrets, tokens, or API keys in staged files
- `.env` file staged
- `print()` statements (use `logging`)
- `os.path` (use `pathlib.Path`)
- Missing type hints on new functions
- Failing tests (`uv run pytest`)
- `TODO` / `FIXME` left in committed code

## Step 3 — Choose the commit type

| Type | When to use |
|------|-------------|
| `feat` | A new capability visible to the system (new module, new function, new behaviour) |
| `fix` | Corrects a bug — something was broken and now it isn't |
| `test` | Adds or updates tests with no production code change |
| `chore` | Tooling, config, dependencies, CI — nothing that affects runtime behaviour |
| `refactor` | Restructures existing code without changing behaviour or adding tests |
| `docs` | Changes to `.md` files, docstrings, or comments only |

**Rules:**
- `feat` is not `chore`. Adding `pyproject.toml` is `chore`. Adding `claude_extractor.py` is `feat`.
- A commit that adds both a feature and its tests is `feat`, not `test`.
- If it touches production code AND config, use the type that describes the production change.

## Step 4 — Write the message

Format: `type(scope): short description`

- Scope matches the phase or module: `phase-1`, `models`, `scraper`, `extractor`, `matcher`, `notifier`, `orchestrator`
- Description: imperative mood, lowercase, no period — "add retry logic" not "Added retry logic."
- 72 characters max on the subject line
- If more context is needed, leave a blank line then add a body

**Examples:**
```
feat(phase-2): add JobPosting dataclass with dedup key logic
fix(scraper): return None on 403 instead of raising
test(matcher): add threshold boundary tests
chore(phase-1): initialise project scaffold and pyproject.toml
refactor(store): extract upsert helper to reduce duplication
docs(setup): add Supabase table creation SQL
```

## Step 5 — Stage and commit

```bash
git add -p          # review every hunk interactively — never git add .
git diff --cached   # final check of exactly what will be committed
git commit -m "type(scope): description"
```

After committing, run `git log --oneline -5` to confirm the message looks right.
