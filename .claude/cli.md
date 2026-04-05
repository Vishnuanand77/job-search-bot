# Claude Code — CLI Reference

Sourced from the official Claude Code docs (code.claude.com/docs/en/cli-reference).
Filtered to commands relevant for day-to-day development work on this project.
Run `/help` inside any session to see all available commands including your custom
ones from `.claude/commands/`.

---

## Installation & Auth

```bash
# Install globally
npm install -g @anthropic-ai/claude-code

# Log in (opens browser)
claude auth login

# Log in with API key instead of subscription
claude auth login --console

# Check login status
claude auth status

# Log out
claude auth logout

# Update to latest version
claude update

# Diagnose installation issues
claude doctor
```

---

## Starting a Session

```bash
# Start interactive session in current directory
claude

# Start with an initial prompt
claude "explain this codebase"

# Start in plan mode (read-only analysis first, no edits)
claude --permission-mode plan

# Start and auto-accept all file edits (no prompts)
claude --permission-mode acceptEdits

# Start with a named session (easier to resume later)
claude -n "phase-3-scraper"

# Set the model for the session
claude --model claude-sonnet-4-6
claude --model claude-opus-4-6

# Append custom rules to the system prompt for this session
claude --append-system-prompt "Always write tests before implementation"
```

---

## Resuming & Continuing Sessions

```bash
# Continue the most recent session in this directory
claude -c
claude --continue

# Resume a session by name or ID
claude -r "phase-3-scraper"
claude --resume "phase-3-scraper"

# Resume and fork (creates new session ID, preserves original)
claude --resume "phase-3-scraper" --fork-session

# Resume a session linked to a GitHub PR
claude --from-pr 42
claude --from-pr https://github.com/you/job-scout/pull/42
```

---

## Non-Interactive (Print) Mode

Runs a single query, prints the result, and exits. Useful for scripting
or quick one-off tasks without entering a full session.

```bash
# Run a query and exit
claude -p "summarise the orchestrator.py module"

# Pipe file content into Claude
cat src/job_scout/orchestrator.py | claude -p "review this for issues"

# Run against a file reference
claude -p "what does this function do" < src/job_scout/matcher/claude_matcher.py

# Continue the last session non-interactively
claude -c -p "check for any type errors in the last file you edited"

# Limit API spend (safety net for scripted calls)
claude -p --max-budget-usd 0.50 "refactor the dispatcher module"

# Limit number of agentic turns
claude -p --max-turns 5 "add docstrings to all functions in models.py"
```

---

## In-Session Slash Commands

Type these at the prompt inside an active Claude Code session.

### Navigation & Session Management

| Command | What it does |
|---|---|
| `/help` | Show all available commands, including your custom `.claude/commands/` ones |
| `/clear` | Clear conversation history and reset context. Aliases: `/reset`, `/new` |
| `/compact` | Compress conversation history to free up context window |
| `/exit` | Exit the session. Alias: `/quit` |
| `/resume [session]` | Switch to a different session by name or ID |
| `/rename [name]` | Rename the current session |
| `/branch` | Fork the conversation at this point. Alias: `/fork` |
| `/rewind` | Rewind conversation and code to a previous checkpoint. Alias: `/checkpoint` |
| `/export [filename]` | Export conversation as plain text |

### Planning & Thinking

| Command | What it does |
|---|---|
| `/plan [description]` | Enter plan mode — Claude analyses and plans without making edits. Essential before starting a new phase. Example: `/plan implement the HTTP scraper` |
| `/effort [low\|medium\|high\|max]` | Adjust how hard Claude thinks. Use `high` for complex matching logic, `low` for simple edits |

### Code & Git

| Command | What it does |
|---|---|
| `/diff` | Interactive diff viewer — see uncommitted changes and per-turn diffs |
| `/pr-comments [PR]` | Fetch and display GitHub PR comments. Auto-detects current branch PR |
| `/security-review` | Scan pending changes for security vulnerabilities |

### Context & Cost

| Command | What it does |
|---|---|
| `/context` | Visualise context window usage. Shows warnings if you're approaching the limit |
| `/cost` | Show token usage and cost for the current session |
| `/copy [N]` | Copy last response to clipboard. `/copy 2` copies second-to-last |

### Configuration

| Command | What it does |
|---|---|
| `/config` | Open settings (theme, model, output style). Alias: `/settings` |
| `/model [model]` | Switch model mid-session without restarting |
| `/permissions` | Manage tool permission rules (allow/ask/deny) |
| `/memory` | Edit `CLAUDE.md` memory files and manage auto-memory entries |
| `/hooks` | View configured hook rules |

### Utilities

| Command | What it does |
|---|---|
| `/init` | Generate a `CLAUDE.md` for the current project |
| `/insights` | Generate a report on your Claude Code usage patterns |
| `/doctor` | Diagnose installation issues mid-session |
| `/feedback` | Submit feedback or a bug report. Alias: `/bug` |
| `/btw <question>` | Ask a quick side question without adding it to the conversation history |

---

## File & Directory References

Inside any session, prefix a path with `@` to reference it directly in your prompt:

```
# Ask about a specific file
Review @src/job_scout/matcher/claude_matcher.py for issues

# Ask about a directory
What test coverage is missing in @tests/?

# Reference multiple files
Compare @src/job_scout/scraper/http_scraper.py and @src/job_scout/scraper/playwright_scraper.py
```

---

## Shell Commands Inside a Session

Prefix with `!` to run a shell command directly without leaving the session:

```
# Run tests
!uv run pytest tests/test_claude_matcher.py -v

# Check git status
!git status

# Run the dry-run
!DRY_RUN=true uv run python -m job_scout.orchestrator

# Check coverage
!uv run pytest --cov=src --cov-report=term-missing
```

---

## Permission Modes

Control how much Claude can do without asking for confirmation.

| Mode | Behaviour | When to use |
|---|---|---|
| `default` | Asks before editing files or running commands | Normal development |
| `plan` | Read-only — no edits, analyses and plans only | Starting a new phase, reviewing architecture |
| `acceptEdits` | Auto-accepts file edits, still asks for shell commands | Writing code quickly |
| `auto` | Automatically decides based on risk (Team/Enterprise only) | Trusted automation |
| `bypassPermissions` | Skips all prompts — use with care | Scripted CI runs only |

Set at startup:
```bash
claude --permission-mode plan
claude --permission-mode acceptEdits
```

Or switch mid-session with `Shift+Tab` to cycle through modes.

---

## Useful CLI Flags for This Project

```bash
# Start with plan mode — good for beginning a new build phase
claude --permission-mode plan -n "phase-4-extraction"

# Auto-accept edits, skip the prompt for every file change
claude --permission-mode acceptEdits

# Append a reminder to always follow TDD
claude --append-system-prompt "Follow the Red-Yellow-Green TDD cycle. Write failing test first."

# Debug MCP or API issues
claude --debug "api,mcp"

# Disable all custom commands for a clean session
claude --disable-slash-commands

# Run a scripted task with a spend cap
claude -p --max-budget-usd 1.00 --max-turns 10 "write tests for the dispatcher module"
```

---

## Keyboard Shortcuts (Interactive Mode)

| Shortcut | Action |
|---|---|
| `Ctrl+C` | Interrupt current response (keeps session alive) |
| `Ctrl+D` | End session |
| `Shift+Tab` | Cycle through permission modes |
| `↑` / `↓` | Navigate prompt history |

---

## Custom Commands in This Project

These are defined in `.claude/commands/` and appear when you type `/`:

| Command | File | What it does |
|---|---|---|
| `/pr-review` | `.claude/commands/pr-review.md` | Run the full PR checklist before opening a PR |
| `/test` | `.claude/commands/test.md` | Common pytest commands for this project |

---

## Recommended Workflow Per Phase

```bash
# 1. Start in plan mode — understand the phase before writing anything
claude --permission-mode plan -n "phase-N-description"

# 2. Inside the session, read the plan
/plan [describe what this phase builds]

# 3. Switch to edit mode when ready to implement
# Use Shift+Tab to cycle to acceptEdits

# 4. Check context usage periodically
/context

# 5. Run tests inline
!uv run pytest --cov=src --cov-report=term-missing

# 6. Before opening a PR
/pr-review

# 7. Check cost before ending long sessions
/cost
```