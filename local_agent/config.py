from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AgentConfig:
    workspace: Path
    model: str
    verifier_model: str
    max_steps: int
    shell_timeout_seconds: int
    db_path: Path


def load_config() -> AgentConfig:
    load_dotenv()
    workspace = Path.cwd().resolve()
    model = os.getenv("AGENT_MODEL", "gpt-5.1")
    verifier_model = os.getenv("AGENT_VERIFIER_MODEL", model)
    max_steps = int(os.getenv("AGENT_MAX_STEPS", "25"))
    shell_timeout_seconds = int(os.getenv("AGENT_SHELL_TIMEOUT", "30"))
    db_path = workspace / ".agent" / "sessions.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return AgentConfig(
        workspace=workspace,
        model=model,
        verifier_model=verifier_model,
        max_steps=max_steps,
        shell_timeout_seconds=shell_timeout_seconds,
        db_path=db_path,
    )
