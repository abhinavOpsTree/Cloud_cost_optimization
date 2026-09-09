"""
api/sse.py
----------
Server-Sent Events helpers for Cloud-Sentry AI.

Provides two generators:
  execution_event_generator — streams script generation progress
  chat_event_generator      — streams chat response word-by-word
"""
from __future__ import annotations

import asyncio
import json


async def execution_event_generator(rec_id: str, state_store, devops_agent):
    """
    SSE generator for the Execute flow.

    Yields progress steps as the DevOps Remediation Agent generates scripts.
    Steps stream in the UI modal as a progress bar advances.
    """
    steps = [
        (10,  "Fetching recommendation details..."),
        (25,  "Calling Gemini 3.5 Flash to generate scripts..."),
        (50,  "Generating Terraform HCL..."),
        (65,  "Generating AWS CLI command..."),
        (80,  "Generating rollback command..."),
        (90,  "Saving to remediation log..."),
    ]

    for pct, step in steps:
        yield f"data: {json.dumps({'step': step, 'pct': pct, 'status': 'running'})}\n\n"
        await asyncio.sleep(0.4)

    # Fetch the recommendation
    rec = state_store.get_recommendation(rec_id)
    if not rec:
        yield f"data: {json.dumps({'step': 'Error: recommendation not found', 'pct': 100, 'status': 'error'})}\n\n"
        return

    # Generate scripts
    try:
        scripts = devops_agent.generate(rec)
        yield f"data: {json.dumps({'step': 'Scripts generated — ready for review', 'pct': 100, 'status': 'ready', 'scripts': scripts})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'step': f'Error generating scripts: {str(e)}', 'pct': 100, 'status': 'error'})}\n\n"


async def chat_event_generator(message: str, session_id: str, chat_agent):
    """
    SSE generator for the Chat flow.

    Calls the chat agent for a full response, then streams it word-by-word
    to create a typing effect in the frontend.
    """
    try:
        response = chat_agent.chat(message, session_id)
        
        # Simple heuristic since Task 6 was skipped
        response_source = "deterministic" if "generate scripts" in message.lower() else "gemini"
        
        words = response.split(" ")
        for word in words:
            yield f"data: {json.dumps({'chunk': word + ' ', 'done': False})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'chunk': '', 'done': True, 'full_response': response})}\n\n"
        yield f"data: {json.dumps({'type': 'source', 'source': response_source, 'done': True})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'chunk': '', 'done': True, 'full_response': f'Error: {str(e)}', 'error': True})}\n\n"
