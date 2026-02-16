from __future__ import annotations

import re

class PolicyError(ValueError):
    pass

_BLOCKED_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+checkout\s+--\b", re.IGNORECASE),
]

def validate_shell_command(command: str) -> None:
    stripped = command.strip()
    if not stripped:
        raise PolicyError("Shell command is empty.")
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern.search(stripped):
            raise PolicyError(f"Blocked shell command pattern: {pattern.pattern}")
