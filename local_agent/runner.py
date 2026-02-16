from __future__ import annotations

import argparse
import uuid

from openai import OpenAI

from local_agent.config import load_config
from local_agent.memory import SessionStore
from local_agent.orchestrator import run_once
from local_agent.ui import (
    create_console,
    show_goodbye,
    show_info,
    show_result,
    show_startup,
    show_tool_error,
    show_tool_step,
    show_verify_error,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent-bot", description="Hacky CLI Bot")
    parser.add_argument("--session", default="default", help="Session name for memory store")
    parser.add_argument("--session-id", help="Backward-compatible alias for --session")
    parser.add_argument("--prompt", help="Single prompt mode")
    args = parser.parse_args()

    cfg = load_config()
    session_id = args.session_id or args.session or str(uuid.uuid4())
    store = SessionStore(cfg.db_path)
    client = OpenAI()
    console = create_console()

    show_startup(console, session_id)

    if args.prompt:
        result = run_once(
            user_input=args.prompt,
            session_id=session_id,
            cfg=cfg,
            store=store,
            client=client,
            on_tool_step=lambda step, tool: show_tool_step(console, step, tool),
            on_tool_error=lambda msg: show_tool_error(console, msg),
            on_verify_error=lambda msg: show_verify_error(console, msg),
            on_info=lambda msg: show_info(console, msg),
        )
        show_result(console, result)
        return 0

    while True:
        try:
            user_input = console.input("[prompt]$ [/prompt]").strip()
        except (EOFError, KeyboardInterrupt):
            show_goodbye(console)
            return 0
        if not user_input:
            continue
        if user_input == "/exit":
            show_goodbye(console)
            return 0
        if user_input == "/reset":
            store.clear(session_id)
            show_info(console, f"Cleared session: {session_id}")
            continue
        try:
            result = run_once(
                user_input=user_input,
                session_id=session_id,
                cfg=cfg,
                store=store,
                client=client,
                on_tool_step=lambda step, tool: show_tool_step(console, step, tool),
                on_tool_error=lambda msg: show_tool_error(console, msg),
                on_verify_error=lambda msg: show_verify_error(console, msg),
                on_info=lambda msg: show_info(console, msg),
            )
        except Exception as exc:  # pragma: no cover
            result = f"Runtime error: {exc}"
        show_result(console, result)

