from __future__ import annotations

from openai import APIError, OpenAI

from local_agent.config import AgentConfig
from local_agent.tools import compact_json

VERIFIER_SYSTEM_PROMPT = """You are a cautious code verifier bot.
Given a user request, changed files, and verification outputs, assess whether the changes appear correct.
Respond in plain text with:
1) Verdict: PASS / NEEDS_REVIEW
2) Why (1-3 bullets)
3) Any risky assumptions or missing checks
Keep it concise.
"""


def run_verifier_bot(
    client: OpenAI,
    cfg: AgentConfig,
    user_request: str,
    edited_files: list[str],
    verify_result: dict | None,
    context_snippet: str = "",
) -> str:
    verify_summary = "none"
    if verify_result is not None:
        verify_summary = compact_json(verify_result)
    verifier_input = (
        f"User request: {user_request}\n"
        f"Edited files: {edited_files}\n"
        f"Compile verification: {verify_summary}\n"
        f"Recent context:\n{context_snippet or 'none'}\n"
    )
    try:
        response = client.chat.completions.create(
            model=cfg.verifier_model,
            messages=[
                {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": verifier_input},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        return (response.choices[0].message.content or "").strip() or "Verifier returned empty response."
    except APIError as exc:
        return f"Verifier bot failed: {exc}"
