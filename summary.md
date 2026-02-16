# Project Summary: Local Coding Agent

## Overview
This project implements a local Python coding agent with a terminal-based UI, tool-use orchestration loop, and a secondary verifier bot. It is designed for safe, interactive code editing and verification, leveraging OpenAI models for orchestration and verification.

## Key Features
- **Interactive CLI**: Hacker-style green/black terminal UI with ASCII banner and session commands (`/reset`, `/exit`).
- **Tool-Use Loop**: The agent alternates between model-driven actions (`message` or `tool`) and tool execution.
- **Available Tools**:
  - `list_files`: List files in a directory.
  - `read_file`: Read file contents by line range.
  - `write_file`: Write full file content.
  - `patch_file`: Targeted file edits by text replacement.
  - `search_text`: Search for text patterns, excluding binary and large (>1MB) files.
  - `run_shell`: Run shell commands with safety policy enforcement.
- **Safety Policy**: Blocks dangerous shell commands (e.g., `rm -rf /`, `sudo`, `shutdown`).
- **Verification**:
  - Auto-verifies code after edits (compilation, etc.).
  - Secondary verifier bot reviews changes and outputs a concise verdict.
- **Session Memory**: SQLite-backed message history per session.
- **Configurable**: Uses `.env` for API keys and environment variables.

## Project Structure
- `main.py`: Entry point, runs the agent.
- `local_agent/`: Core logic (tools, UI, config, memory, orchestrator, verifier, policy).
- `tests/`: Contains behavioral tests (e.g., `test_search_text_behavior.py`).
- `.agent/`: SQLite session database.
- `requirements.txt`: Python dependencies.

## Behavioral Verification
- The `tests/test_search_text_behavior.py` file verifies that `search_text` correctly excludes binary and large files in both `ripgrep` and fallback search paths.
- Verification is run automatically after code edits and can be run manually for regression testing.

## Setup & Usage
1. Add your `OPENAI_API_KEY` to `.env`.
2. Install dependencies: `python3 -m pip install -r requirements.txt`
3. Run interactively: `python3 main.py`

## Notable Files
- `README.md`: Main documentation and usage instructions.
- `summary.md`: (This file) High-level project summary.
- `tests/test_search_text_behavior.py`: Behavioral test for search tool correctness.

## Extensibility
The agent is modular and can be extended with new tools, policies, or verification steps as needed.
