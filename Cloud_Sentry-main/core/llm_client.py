"""
core/llm_client.py
------------------
Central Gemini API wrapper for Cloud-Sentry AI.

ALL Gemini calls in the application must go through call_gemini() or
call_gemini_with_retry(). Direct SDK calls are not permitted elsewhere.

Rules:
  - Package:   google-genai (NOT google-generativeai)
  - Import:    from google import genai
  - Client:    genai.Client(api_key=os.environ["GEMINI_API_KEY"])
  - Primary:   gemini-3.6-flash
  - Fallback:  gemini-3.5-flash
  - NEVER use: gemini-2.0-flash (retired June 1 2026)
  - Hard stop: 50 calls per run — remaining instances get FLAGGED
  - On failure: return safe default, NEVER crash, NEVER raise unhandled

Every call is logged to the llm_usage SQLite table for cost tracking.
"""
from __future__ import annotations

import json
import os
import re
import threading
import traceback
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-3.5-flash"

# Hard budget ceiling per run
MAX_CALLS_PER_RUN = 50
MAX_TOKENS_PER_RUN = 50_000

# ---------------------------------------------------------------------------
# Gemini client (lazy singleton)
# ---------------------------------------------------------------------------

_client = None
_call_count = 0         # resets per run
_token_count = 0        # approximate
_call_count_lock = threading.Lock()  # guards _call_count and _token_count


def get_client():
    """Return the singleton Gemini client. Creates it on first call."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. "
                "Create a .env file with GEMINI_API_KEY=your_key"
            )
        from google import genai  # type: ignore
        _client = genai.Client(api_key=api_key)
    return _client


def reset_run_counters() -> None:
    """Call at the start of each analysis run to reset budget counters."""
    global _call_count, _token_count
    with _call_count_lock:
        _call_count = 0
        _token_count = 0


def get_call_count() -> int:
    with _call_count_lock:
        return _call_count


# ---------------------------------------------------------------------------
# Safe default responses (returned when Gemini unavailable or budget exceeded)
# ---------------------------------------------------------------------------

_SAFE_DEFAULT_JSON = json.dumps({
    "safe": False,
    "confidence": 0.0,
    "reason": "AI reasoning unavailable — conservative flag applied. System defaults to caution.",
})

_SAFE_DEFAULT_TEXT = "AI reasoning unavailable. System defaults to caution."

_BUDGET_JSON = json.dumps({
    "safe": False,
    "confidence": 0.0,
    "reason": "LLM budget exceeded — defaulting to FLAGGED for safety.",
})

_BUDGET_TEXT = "LLM budget exceeded for this run. Remaining instances flagged for human review."


# ---------------------------------------------------------------------------
# Core call function
# ---------------------------------------------------------------------------

def call_gemini(
    prompt: str,
    expect_json: bool = False,
    agent: str = "unknown",
    resource_id: Optional[str] = None,
    run_id: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    Make a single Gemini API call.

    Args:
        prompt:      The full prompt to send
        expect_json: If True, strips markdown code fences from response
        agent:       Name of the calling agent (for logging)
        resource_id: The resource being evaluated (for logging)
        run_id:      The current analysis run ID (for logging)
        model:       Override model (defaults to PRIMARY_MODEL)

    Returns:
        The response text (or a safe default string on failure).
        NEVER raises an unhandled exception.

    Notes:
        - Logs every call to llm_usage SQLite table
        - Hard stops if MAX_CALLS_PER_RUN exceeded
        - Tries PRIMARY_MODEL first, then FALLBACK_MODEL
    """
    global _call_count, _token_count

    # Budget check — atomic check-and-increment under lock
    with _call_count_lock:
        if _call_count >= MAX_CALLS_PER_RUN:
            print(f"[LLM] Budget ceiling reached ({MAX_CALLS_PER_RUN} calls). "
                  f"Agent={agent}, resource={resource_id} -> FLAGGED")
            return _BUDGET_JSON if expect_json else _BUDGET_TEXT

        if _token_count >= MAX_TOKENS_PER_RUN:
            print(f"[LLM] Token budget exceeded ({MAX_TOKENS_PER_RUN}). "
                  f"Agent={agent} -> FLAGGED")
            return _BUDGET_JSON if expect_json else _BUDGET_TEXT

        # Reserve our call slot before releasing the lock
        _call_count += 1
        current_call_num = _call_count

    use_model = model or PRIMARY_MODEL
    tried_fallback = False

    for attempt in range(3):
        # Switch to fallback after 2 failed attempts on primary
        if attempt == 2 and not tried_fallback:
            use_model = FALLBACK_MODEL
            tried_fallback = True
            print(f"[LLM] Switching to fallback model {FALLBACK_MODEL}")

        try:
            client = get_client()
            response = client.models.generate_content(
                model=use_model,
                contents=prompt,
            )
            text = response.text or ""

            # Approximate token counting (word count proxy)
            input_tokens = len(prompt.split())
            output_tokens = len(text.split())

            # Update token count under lock (call slot already reserved above)
            with _call_count_lock:
                _token_count += input_tokens + output_tokens

            # Log to SQLite (best effort — don't crash if DB is unavailable)
            try:
                from core.state_store import StateStore
                StateStore().log_llm_usage(
                    agent=agent,
                    model=use_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    resource_id=resource_id,
                    run_id=run_id,
                )
            except Exception as db_err:
                print(f"[LLM] Usage logging failed (non-fatal): {db_err}")

            # Strip markdown fences if JSON expected
            if expect_json:
                text = re.sub(r"```(?:json)?\s*", "", text)
                text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
                text = text.strip()

            print(f"[LLM] {agent} | model={use_model} | "
                  f"~{input_tokens}in/{output_tokens}out tokens | "
                  f"run_calls={current_call_num}")
            return text

        except Exception as e:
            print(f"[LLM] Attempt {attempt + 1} failed for agent={agent}: {e}")
            if attempt == 2:
                # All retries exhausted
                print(f"[LLM] All retries failed. Returning safe default.")
                print(traceback.format_exc())

    return _SAFE_DEFAULT_JSON if expect_json else _SAFE_DEFAULT_TEXT


def call_gemini_with_retry(
    prompt: str,
    expect_json: bool = False,
    agent: str = "unknown",
    resource_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> str:
    """
    Convenience wrapper — delegates to call_gemini which already handles retries.
    Kept for API compatibility with code that calls this variant.
    NEVER raises an unhandled exception.
    """
    return call_gemini(
        prompt=prompt,
        expect_json=expect_json,
        agent=agent,
        resource_id=resource_id,
        run_id=run_id,
    )
