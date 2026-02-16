# Local Coding Agent (Current)

Local Python coding agent with a green/black terminal UI, tool-use loop, and a second verifier bot.

## Current Features

- OpenAI-driven orchestration loop (`message` or `tool` action model)
- Tooling:
  - `list_files`
  - `read_file`
  - `write_file`
  - `patch_file`
  - `search_text`
  - `run_shell`
- Safety policy for dangerous shell commands
- Auto-compile verification after edit tools (`write_file`, `patch_file`)
- Secondary verifier bot pass after code edits
- SQLite-backed session memory
- Interactive CLI with hacker-style green/black theme and ASCII banner (`ui.py`)
- Session commands:
  - `/reset`
  - `/exit`

## Project Layout

- `/Users/arjun/PycharmProjects/codex-agent-1.0/main.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/config.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/ui.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/runner.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/orchestrator.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/verifier.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/tools.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/policy.py`
- `/Users/arjun/PycharmProjects/codex-agent-1.0/local_agent/memory.py`

## Setup

1. Ensure `.env` contains `OPENAI_API_KEY`.
2. Install dependencies:
   - `python3 -m pip install -r requirements.txt`

## Running

1. Interactive mode:
   - `python3 main.py`
2. Single prompt:
   - `python3 main.py --prompt "List files in this project"`
3. Custom session:
   - `python3 main.py --session my-session`
4. Backward-compatible alias:
   - `python3 main.py --session-id my-session`

## Environment Variables

- `AGENT_MODEL` (default: `gpt-5.1`)
- `AGENT_VERIFIER_MODEL` (default: same as `AGENT_MODEL`)
- `AGENT_MAX_STEPS` (default: `25`)
- `AGENT_SHELL_TIMEOUT` (default: `30`)

## Runtime Workflow

1. `runner.py` handles CLI loop + command routing.
2. `orchestrator.py` loads context and drives model/tool steps.
3. Tool results are compacted and fed back into the model.
4. On edit tools:
   - run both compile and behavioral verification:
     - `python3 -m compileall -q .`
     - `PYTHONPATH=. python3 -m unittest tests/test_search_text_behavior.py -v`
   - Returns a structured verify result with pass/fail for each step, and fails overall if either step fails.
   - call `verifier.py` for a second verification verdict
5. Step budget split:
   - execution phase uses `max_steps - 4`
   - last 4 steps are reserved for verification/finalization
6. Save assistant output to SQLite session memory.

Session DB path: `/Users/arjun/PycharmProjects/codex-agent-1.0/.agent/sessions.sqlite3`

## Notes

- `search_text` and `list_files` prefer `rg` when installed; otherwise they use Python fallbacks.
- Agent responses are JSON-constrained internally, with a retry path if model output is malformed.
