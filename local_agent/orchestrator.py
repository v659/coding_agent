from __future__ import annotations

import json
import re
from typing import Any, Callable

from openai import APIError, OpenAI
from pydantic import BaseModel, ValidationError

from local_agent.config import AgentConfig
from local_agent.memory import SessionStore
from local_agent.tools import TOOL_SPECS, ToolError, compact_json, dispatch_tool, run_shell
from local_agent.verifier import run_verifier_bot

SYSTEM_PROMPT = """You are a pragmatic local coding agent.
You can either reply to the user or call exactly one tool at a time.
Always return a JSON object with this schema:
{"type":"message","content":"..."} OR {"type":"tool","name":"tool_name","args":{...}}
Rules:
- Use tools before making assumptions.
- Keep tool args valid for the schema.
- Prefer `patch_file` over `write_file` for targeted edits to keep responses small and reliable.
- Never output markdown fences.
- Do not output planning/status-only messages like "I will now...".
- If the user asks for code changes, execute them directly using tools in this turn.
- After successful code edits (`write_file` or `patch_file`), run verification.
- If done, return type=message with a concise answer.
Available tools:
"""

_KNOWN_TOOL_NAMES = {tool["name"] for tool in TOOL_SPECS}
_TOOL_REQUIRED_ARGS = {
    tool["name"]: tool.get("input_schema", {}).get("required", []) for tool in TOOL_SPECS
}
_MAX_HISTORY_MESSAGES = 6
_MAX_HISTORY_CHARS = 1500
_MAX_TOOL_RESULT_CHARS = 1800
_VERIFICATION_RESERVED_STEPS = 4


class ToolAction(BaseModel):
    type: str
    name: str
    args: dict[str, Any]


class MessageAction(BaseModel):
    type: str
    content: str


def _clip(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + "...(truncated)"


def _short_json(data: dict[str, Any], max_len: int = 1200) -> str:
    return _clip(compact_json(data), max_len)


def _extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: find the first balanced JSON object and parse it.
    start = raw.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found in model response.", raw, 0)

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start : idx + 1]
                return json.loads(candidate)

    raise json.JSONDecodeError("Unterminated JSON object in model response.", raw, start)


def _model_step(client: OpenAI, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    def _request(input_messages: list[dict[str, str]], max_tokens: int = 1000) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=input_messages,
            temperature=0.0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return (response.choices[0].message.content or "").strip()

    try:
        return _extract_json(_request(messages))
    except APIError as exc:
        raise RuntimeError(f"Model/API error for `{model}`: {exc}") from exc
    except json.JSONDecodeError as exc:
        retry_messages = messages + [
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Return exactly one JSON object now with schema "
                    '{"type":"message","content":"..."} OR {"type":"tool","name":"tool_name","args":{...}}. '
                    "No extra text."
                ),
            }
        ]
        try:
            return _extract_json(_request(retry_messages, max_tokens=700))
        except (APIError, json.JSONDecodeError) as retry_exc:
            # Last-resort retry with reduced context to avoid truncated JSON responses.
            reduced_messages = [messages[0]] + messages[-2:]
            try:
                reduced_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "If you need to edit code, use patch_file with small find/replace chunks. "
                            "Do not send large full-file content."
                        ),
                    }
                )
                return _extract_json(_request(reduced_messages, max_tokens=500))
            except (APIError, json.JSONDecodeError):
                raise RuntimeError(f"Model response was not valid JSON. Parse detail: {_clip(str(exc), 220)}") from retry_exc


def _normalize_action(action_data: dict[str, Any]) -> dict[str, Any]:
    action_type = action_data.get("type")
    if action_type in {"tool", "message"}:
        return action_data
    if action_type in _KNOWN_TOOL_NAMES:
        normalized = dict(action_data)
        normalized["type"] = "tool"
        normalized["name"] = action_type
        normalized.setdefault("args", {})
        return normalized
    if (
        isinstance(action_data.get("name"), str)
        and action_data["name"] in _KNOWN_TOOL_NAMES
        and isinstance(action_data.get("args"), dict)
    ):
        normalized = dict(action_data)
        normalized["type"] = "tool"
        return normalized
    return action_data


def _extract_first_file_path(text: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_\-./]+\.py)\b", text)
    return match.group(1) if match else None


def _derive_pattern_from_request(text: str) -> str | None:
    for token in re.findall(r"`([^`]+)`", text):
        cleaned = token.strip()
        if cleaned:
            return cleaned
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", text)
    return match.group(1) if match else None


def _repair_tool_args(tool_name: str, args: dict[str, Any], user_input: str) -> dict[str, Any]:
    repaired = dict(args)
    required = _TOOL_REQUIRED_ARGS.get(tool_name, [])
    if "path" in required and "path" not in repaired:
        guessed_path = _extract_first_file_path(user_input)
        if guessed_path:
            repaired["path"] = guessed_path
    if tool_name == "search_text" and "pattern" not in repaired:
        guessed_pattern = _derive_pattern_from_request(user_input)
        if guessed_pattern:
            repaired["pattern"] = guessed_pattern
    return repaired


def _is_progress_only_message(content: str) -> bool:
    lower = content.lower().strip()
    progress_markers = [
        "i will now",
        "i'll now",
        "i will",
        "i have the full",
        "i have gathered",
        "i have located",
        "i can now",
        "i will proceed",
        "proceed with",
    ]
    completion_markers = [
        "done",
        "completed",
        "updated",
        "changed",
        "verification",
        "compiled",
        "summary",
    ]
    return any(marker in lower for marker in progress_markers) and not any(
        marker in lower for marker in completion_markers
    )


def _compact_tool_result_payload(tool_result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(tool_result)
    result = payload.get("result")
    if not isinstance(result, dict):
        return payload
    result = dict(result)
    for key in ("stdout", "stderr", "content"):
        if isinstance(result.get(key), str):
            result[key] = _clip(result[key], 1500)
    for key in ("files", "matches"):
        value = result.get(key)
        if isinstance(value, list) and len(value) > 40:
            result[key] = value[:40]
            result[f"{key}_truncated"] = len(value) - 40
    payload["result"] = result
    return payload


def _auto_verify(cfg: AgentConfig) -> dict[str, Any]:
    compile_result = run_shell(
        workspace=cfg.workspace,
        command="python3 -m compileall -q .",
        timeout_seconds=cfg.shell_timeout_seconds,
    )
    behavior_result = run_shell(
        workspace=cfg.workspace,
        command="PYTHONPATH=. python3 -m unittest tests/test_search_text_behavior.py -v",
        timeout_seconds=cfg.shell_timeout_seconds,
    )
    return {
        "compile": {
            "pass": compile_result.get("returncode", 1) == 0,
            "result": compile_result,
        },
        "behavior": {
            "pass": behavior_result.get("returncode", 1) == 0,
            "result": behavior_result,
        },
        "overall_pass": compile_result.get("returncode", 1) == 0 and behavior_result.get("returncode", 1) == 0,
    }


def _build_verifier_context(history: list[dict[str, str]], max_items: int = 8) -> str:
    relevant = [item for item in history if item.get("role") in {"user", "assistant"}]
    tail = relevant[-max_items:]
    lines: list[str] = []
    for item in tail:
        role = item.get("role", "unknown")
        content = _clip(item.get("content", ""), 220)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def run_once(
    user_input: str,
    session_id: str,
    cfg: AgentConfig,
    store: SessionStore,
    client: OpenAI,
    on_tool_step: Callable[[int, str], None] | None = None,
    on_tool_error: Callable[[str], None] | None = None,
    on_verify_error: Callable[[str], None] | None = None,
    on_info: Callable[[str], None] | None = None,
) -> str:
    total_steps = max(1, cfg.max_steps)
    reserved_steps = min(_VERIFICATION_RESERVED_STEPS, max(total_steps - 1, 0))
    execution_step_limit = max(1, total_steps - reserved_steps)

    history = [{"role": "system", "content": SYSTEM_PROMPT + compact_json(TOOL_SPECS)}]
    for message in store.load(session_id=session_id, limit=_MAX_HISTORY_MESSAGES):
        history.append({"role": message.role, "content": _clip(message.content, _MAX_HISTORY_CHARS)})

    store.append(session_id, "user", user_input)
    history.append({"role": "user", "content": user_input})

    edited_files: list[str] = []
    latest_verify_result: dict[str, Any] | None = None
    repeated_error_counts: dict[str, int] = {}

    for step in range(execution_step_limit):
        try:
            action_data = _normalize_action(_model_step(client=client, model=cfg.model, messages=history))
        except RuntimeError as exc:
            message = str(exc)
            store.append(session_id, "assistant", message)
            return message

        action_type = action_data.get("type")
        if action_type == "message":
            try:
                action = MessageAction.model_validate(action_data)
            except ValidationError as exc:
                message = f"Invalid message action: {exc}"
                store.append(session_id, "assistant", message)
                return message

            if _is_progress_only_message(action.content):
                history.append({"role": "assistant", "content": action.content})
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue now and execute concrete tool actions. "
                            "Do not ask for confirmation. Only return final message after edits + verification."
                        ),
                    }
                )
                continue

            final_message = action.content
            if edited_files:
                verifier_summary = _compact_tool_result_payload({"result": latest_verify_result or {}})["result"]
                verifier_context = _build_verifier_context(history)
                verifier = run_verifier_bot(
                    client=client,
                    cfg=cfg,
                    user_request=user_input,
                    edited_files=edited_files,
                    verify_result=verifier_summary,
                    context_snippet=verifier_context,
                )
                final_message = f"{final_message}\n\nVerifier Bot:\n{verifier}"
            store.append(session_id, "assistant", final_message)
            return final_message

        if action_type == "tool":
            try:
                action = ToolAction.model_validate(action_data)
            except ValidationError as exc:
                tool_result = {
                    "ok": False,
                    "tool": action_data.get("name", "unknown"),
                    "error": f"Invalid tool action: {exc}",
                }
                history.append({"role": "assistant", "content": compact_json(action_data)})
                history.append({"role": "user", "content": f"Tool result: {compact_json(tool_result)}"})
                if on_tool_error:
                    on_tool_error(_short_json(tool_result))
                continue

            try:
                result = dispatch_tool(
                    name=action.name,
                    args=_repair_tool_args(action.name, action.args, user_input),
                    workspace=cfg.workspace,
                    shell_timeout_seconds=cfg.shell_timeout_seconds,
                )
                tool_result = {"ok": True, "tool": action.name, "result": result}
            except ToolError as exc:
                tool_result = {"ok": False, "tool": action.name, "error": str(exc)}
            except Exception as exc:  # pragma: no cover
                tool_result = {"ok": False, "tool": action.name, "error": f"Unexpected tool error: {exc}"}

            compact_tool_result = _compact_tool_result_payload(tool_result)
            history.append({"role": "assistant", "content": compact_json(action_data)})
            history.append(
                {
                    "role": "user",
                    "content": f"Tool result: {_clip(compact_json(compact_tool_result), _MAX_TOOL_RESULT_CHARS)}",
                }
            )

            if on_tool_step:
                on_tool_step(step + 1, action.name)

            if not tool_result.get("ok"):
                error_text = str(tool_result.get("error", "unknown"))
                error_sig = f"{action.name}:{error_text}"
                repeated_error_counts[error_sig] = repeated_error_counts.get(error_sig, 0) + 1
                if on_tool_error:
                    on_tool_error(
                        _short_json(
                            {
                                "step": step + 1,
                                "tool": action.name,
                                "args": action.args,
                                "error": error_text,
                            }
                        )
                    )
                required = _TOOL_REQUIRED_ARGS.get(action.name, [])
                if required and "Missing required argument" in error_text:
                    history.append(
                        {
                            "role": "user",
                            "content": (
                                f"Tool call correction: `{action.name}` requires args {required}. "
                                "Retry with valid args immediately."
                            ),
                        }
                    )

                if repeated_error_counts[error_sig] >= 3:
                    message = (
                        f"Aborted repeated failing tool call: {action.name}. "
                        f"Last error: {error_text}. Try /reset and rephrase with explicit file path."
                    )
                    store.append(session_id, "assistant", message)
                    return message
                continue

            if action.name in {"write_file", "patch_file"}:
                path = str((tool_result.get("result") or {}).get("path", ""))
                if path and path not in edited_files:
                    edited_files.append(path)

                latest_verify_result = _auto_verify(cfg)
                verify_payload = {
                    "ok": bool(latest_verify_result.get("overall_pass", False)),
                    "tool": "auto_verify",
                    "result": latest_verify_result,
                }
                compact_verify = _compact_tool_result_payload(verify_payload)
                history.append(
                    {
                        "role": "user",
                        "content": f"Tool result: {_clip(compact_json(compact_verify), _MAX_TOOL_RESULT_CHARS)}",
                    }
                )
                if on_info:
                    on_info(
                        "auto_verify: python3 -m compileall -q . && "
                        "PYTHONPATH=. python3 -m unittest tests/test_search_text_behavior.py -v"
                    )
                if not bool(latest_verify_result.get("overall_pass", False)) and on_verify_error:
                    on_verify_error(_short_json(latest_verify_result))
            continue

        message = f"Unknown action type from model: {action_data}"
        store.append(session_id, "assistant", message)
        return message

    timeout_message = f"Stopped after {cfg.max_steps} steps without a final answer."
    if edited_files:
        if latest_verify_result is None:
            latest_verify_result = _auto_verify(cfg)
            if on_info:
                on_info(
                    "reserved verification phase: python3 -m compileall -q . && "
                    "PYTHONPATH=. python3 -m unittest tests/test_search_text_behavior.py -v"
                )
            if not bool(latest_verify_result.get("overall_pass", False)) and on_verify_error:
                on_verify_error(_short_json(latest_verify_result))
        verifier_summary = _compact_tool_result_payload({"result": latest_verify_result or {}})["result"]
        verifier_context = _build_verifier_context(history)
        verifier = run_verifier_bot(
            client=client,
            cfg=cfg,
            user_request=user_input,
            edited_files=edited_files,
            verify_result=verifier_summary,
            context_snippet=verifier_context,
        )
        timeout_message = f"{timeout_message}\n\nVerifier Bot:\n{verifier}"
    else:
        timeout_message = (
            f"Stopped after execution budget of {execution_step_limit} steps "
            f"(reserved {reserved_steps} for verification/finalization) without a final answer."
        )
    store.append(session_id, "assistant", timeout_message)
    return timeout_message
