from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from local_agent.policy import PolicyError, validate_shell_command


class ToolError(ValueError):
    pass


def _require_arg(args: dict[str, Any], key: str, tool_name: str) -> Any:
    if key not in args:
        raise ToolError(f"Missing required argument `{key}` for tool `{tool_name}`.")
    return args[key]


def _has_rg() -> bool:
    return shutil.which("rg") is not None


def _resolve_path(workspace: Path, raw_path: str) -> Path:
    candidate = (workspace / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ToolError(f"Path escapes workspace: {raw_path}") from exc
    return candidate


def _resolve_path_or_workspace(workspace: Path, raw_path: str) -> Path:
    try:
        return _resolve_path(workspace, raw_path)
    except ToolError:
        return workspace


def _workspace_relative(workspace: Path, raw_path: str) -> str:
    path_obj = Path(raw_path)
    abs_path = path_obj if path_obj.is_absolute() else (workspace / path_obj)
    try:
        return str(abs_path.relative_to(workspace))
    except ValueError:
        return str(path_obj)


def _should_skip_file_for_search(file_path: Path) -> bool:
    try:
        if file_path.stat().st_size > 1_048_576:
            return True
        with open(file_path, "rb") as f:
            first_bytes = f.read(1024)
            if b"\x00" in first_bytes:
                return True
    except OSError:
        return True
    return False


def list_files(workspace: Path, path: str = ".") -> dict[str, Any]:
    target = _resolve_path_or_workspace(workspace, path)
    if not target.exists():
        raise ToolError(f"Path does not exist: {path}")

    files: list[str] = []
    if _has_rg():
        command = ["rg", "--files", str(target)]
        proc = subprocess.run(command, capture_output=True, text=True, check=False, cwd=workspace)
        if proc.returncode not in (0, 1):
            raise ToolError(proc.stderr.strip() or "Failed to list files.")
        files = [line for line in proc.stdout.splitlines() if line.strip()]
        files = [_workspace_relative(workspace, file) for file in files]
    else:
        iterable = [target] if target.is_file() else target.rglob("*")
        for entry in iterable:
            if entry.is_file():
                files.append(str(entry.relative_to(workspace)))

    return {"count": len(files), "files": files[:300]}


def read_file(workspace: Path, path: str, start: int = 1, end: int = 200) -> dict[str, Any]:
    resolved = _resolve_path(workspace, path)
    if not resolved.is_file():
        raise ToolError(f"Not a file: {path}")
    if start < 1 or end < start:
        raise ToolError("Invalid line range.")
    lines = resolved.read_text(encoding="utf-8").splitlines()
    snippet = lines[start - 1 : end]
    return {
        "path": str(resolved.relative_to(workspace)),
        "start": start,
        "end": end,
        "content": "\n".join(snippet),
        "total_lines": len(lines),
    }


def write_file(workspace: Path, path: str, content: str) -> dict[str, Any]:
    resolved = _resolve_path(workspace, path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return {"path": str(resolved.relative_to(workspace)), "bytes_written": len(content.encode("utf-8"))}


def patch_file(
    workspace: Path,
    path: str,
    find: str,
    replace: str,
    expected_replacements: int | None = None,
) -> dict[str, Any]:
    if not find:
        raise ToolError("`find` must not be empty.")
    resolved = _resolve_path(workspace, path)
    if not resolved.is_file():
        raise ToolError(f"Not a file: {path}")
    original = resolved.read_text(encoding="utf-8")
    replacements = original.count(find)
    if replacements == 0:
        raise ToolError("No matches found for `find`.")
    if expected_replacements is not None and replacements != expected_replacements:
        raise ToolError(
            f"Replacement count mismatch. expected={expected_replacements}, actual={replacements}"
        )
    updated = original.replace(find, replace)
    resolved.write_text(updated, encoding="utf-8")
    return {
        "path": str(resolved.relative_to(workspace)),
        "replacements": replacements,
        "bytes_written": len(updated.encode("utf-8")),
    }


def search_text(workspace: Path, pattern: str, path: str = ".") -> dict[str, Any]:
    target = _resolve_path_or_workspace(workspace, path)
    if not target.exists():
        raise ToolError(f"Path does not exist: {path}")

    if _has_rg():
        command = ["rg", "-n", "--max-count", "200", pattern, str(target)]
        proc = subprocess.run(command, capture_output=True, text=True, check=False, cwd=workspace)
        if proc.returncode not in (0, 1):
            raise ToolError(proc.stderr.strip() or "Search failed.")
        matches = proc.stdout.splitlines()
        cleaned = []
        for line in matches[:200]:
            if ":" not in line:
                cleaned.append(line)
                continue
            file_part, rest = line.split(":", 1)
            path_part = file_part.split(":", 1)[0]
            candidate = Path(path_part) if Path(path_part).is_absolute() else (workspace / path_part)
            if candidate.exists() and _should_skip_file_for_search(candidate):
                continue
            rel_file = _workspace_relative(workspace, file_part)
            cleaned.append(f"{rel_file}:{rest}")
        return {"count": len(cleaned), "matches": cleaned}

    try:
        regex = re.compile(pattern)
        search_mode = "regex"
    except re.error:
        regex = None
        search_mode = "literal"

    files_to_scan = [target] if target.is_file() else [p for p in target.rglob("*") if p.is_file()]
    matches: list[str] = []
    for file_path in files_to_scan:
        if _should_skip_file_for_search(file_path):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            is_match = bool(regex.search(line)) if regex else (pattern in line)
            if is_match:
                rel_file = str(file_path.relative_to(workspace))
                matches.append(f"{rel_file}:{lineno}:{line}")
                if len(matches) >= 200:
                    return {"count": len(matches), "matches": matches, "search_mode": search_mode}
    return {"count": len(matches), "matches": matches, "search_mode": search_mode}


def run_shell(workspace: Path, command: str, timeout_seconds: int = 30) -> dict[str, Any]:
    try:
        validate_shell_command(command)
    except PolicyError as exc:
        raise ToolError(str(exc)) from exc
    proc = subprocess.run(
        command,
        cwd=workspace,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-8000:],
    }


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files under a path relative to workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file by line range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer", "default": 1},
                "end": {"type": "integer", "default": 200},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Write full file content to path relative to workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_text",
        "description": "Search text with ripgrep under a path.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}},
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "patch_file",
        "description": "Patch a file by exact text replacement.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "find": {"type": "string"},
                "replace": {"type": "string"},
                "expected_replacements": {"type": "integer"},
            },
            "required": ["path", "find", "replace"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_shell",
        "description": "Run a shell command in workspace with policy checks.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        },
    },
]


def dispatch_tool(name: str, args: dict[str, Any], workspace: Path, shell_timeout_seconds: int) -> dict[str, Any]:
    if name == "list_files":
        return list_files(workspace=workspace, path=args.get("path", "."))
    if name == "read_file":
        path = str(_require_arg(args, "path", name))
        return read_file(
            workspace=workspace,
            path=path,
            start=int(args.get("start", 1)),
            end=int(args.get("end", 200)),
        )
    if name == "write_file":
        return write_file(
            workspace=workspace,
            path=str(_require_arg(args, "path", name)),
            content=str(_require_arg(args, "content", name)),
        )
    if name == "search_text":
        return search_text(
            workspace=workspace,
            pattern=str(_require_arg(args, "pattern", name)),
            path=str(args.get("path", ".")),
        )
    if name == "patch_file":
        expected = args.get("expected_replacements")
        return patch_file(
            workspace=workspace,
            path=str(_require_arg(args, "path", name)),
            find=str(_require_arg(args, "find", name)),
            replace=str(_require_arg(args, "replace", name)),
            expected_replacements=int(expected) if expected is not None else None,
        )
    if name == "run_shell":
        return run_shell(
            workspace=workspace,
            command=str(_require_arg(args, "command", name)),
            timeout_seconds=shell_timeout_seconds,
        )
    raise ToolError(f"Unknown tool: {name}")


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))
