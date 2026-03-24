"""
mas/tools/comfyui.py — ComfyUI workflow submission and polling tools.

comfyui_submit: POST a workflow JSON to /prompt, return the prompt_id.
comfyui_poll:   GET /history/{prompt_id} and return output image paths/URLs.

ComfyUI API contract:
  POST /prompt          { "prompt": <workflow_dict>, "client_id": <str> }
                        → { "prompt_id": <str>, "number": <int>, "node_errors": {} }

  GET  /history/{id}    → { <prompt_id>: { "outputs": { <node_id>: { "images": [...] } } } }
                          Returns {} while the job is still running.

  GET  /queue           → { "queue_running": [...], "queue_pending": [...] }

Environment:
  COMFYUI_HOST  — base URL, default "http://127.0.0.1:8188"
"""
from __future__ import annotations

import os
import uuid
from typing import Any


_DEFAULT_HOST = "http://127.0.0.1:8188"
_CLIENT_ID = str(uuid.uuid4())  # stable for the lifetime of this process


def _host() -> str:
    return os.environ.get("COMFYUI_HOST", _DEFAULT_HOST).rstrip("/")


# ---------------------------------------------------------------------------
# comfyui_submit
# ---------------------------------------------------------------------------

def comfyui_submit(
    workflow: dict,
    client_id: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Submit a workflow to ComfyUI's /prompt endpoint.

    Args:
        workflow: ComfyUI workflow dict (the "prompt" object from the UI export).
        client_id: Client UUID for this submission (defaults to module-level UUID).
        timeout: HTTP request timeout in seconds (default 30).

    Returns:
        dict with keys:
            prompt_id (str): UUID assigned by ComfyUI — use this for polling.
            queue_number (int): Position in queue (0 = currently executing).
            node_errors (dict): Per-node validation errors (empty = clean).
            error (str | None): Error message if submission failed.
    """
    try:
        import httpx
    except ImportError:
        return {"prompt_id": None, "queue_number": None, "node_errors": {},
                "error": "httpx is not installed. Run: pip install httpx"}

    payload = {
        "prompt": workflow,
        "client_id": client_id or _CLIENT_ID,
    }
    url = f"{_host()}/prompt"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return {
            "prompt_id": data.get("prompt_id"),
            "queue_number": data.get("number"),
            "node_errors": data.get("node_errors", {}),
            "error": None,
        }

    except Exception as exc:
        return {"prompt_id": None, "queue_number": None, "node_errors": {}, "error": str(exc)}


# ---------------------------------------------------------------------------
# comfyui_poll
# ---------------------------------------------------------------------------

def comfyui_poll(
    prompt_id: str,
    timeout: int = 10,
) -> dict[str, Any]:
    """
    Poll ComfyUI /history/{prompt_id} for completion status and output images.

    Returns immediately — does NOT block until completion. The caller is
    responsible for polling on an interval (e.g. every 2 seconds).

    Args:
        prompt_id: The UUID returned by comfyui_submit.
        timeout: HTTP request timeout in seconds (default 10).

    Returns:
        dict with keys:
            prompt_id (str): Echo of the input.
            status (str): "pending" | "running" | "complete" | "error".
            outputs (list[dict]): List of { node_id, filename, subfolder, type, url }.
                                  Empty while status is pending/running.
            error (str | None): Error message if the poll itself failed.
    """
    try:
        import httpx
    except ImportError:
        return {"prompt_id": prompt_id, "status": "error", "outputs": [],
                "error": "httpx is not installed. Run: pip install httpx"}

    # Check /history first
    history_url = f"{_host()}/history/{prompt_id}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(history_url)
            resp.raise_for_status()
            history = resp.json()
    except Exception as exc:
        return {"prompt_id": prompt_id, "status": "error", "outputs": [], "error": str(exc)}

    if not history:
        # Not in history yet — check if it's in the queue
        status = _check_queue_status(prompt_id, timeout)
        return {"prompt_id": prompt_id, "status": status, "outputs": [], "error": None}

    # Job is in history → it has completed (ComfyUI only moves to history on finish)
    entry = history.get(prompt_id, {})
    outputs = _extract_outputs(entry.get("outputs", {}))

    # Check for execution errors embedded in the history entry
    status_data = entry.get("status", {})
    if status_data.get("status_str") == "error" or status_data.get("completed") is False:
        messages = status_data.get("messages", [])
        error_msgs = [str(m) for m in messages if "error" in str(m).lower()]
        return {
            "prompt_id": prompt_id,
            "status": "error",
            "outputs": outputs,
            "error": "; ".join(error_msgs) or "ComfyUI reported execution error.",
        }

    return {"prompt_id": prompt_id, "status": "complete", "outputs": outputs, "error": None}


def _check_queue_status(prompt_id: str, timeout: int) -> str:
    """Return 'running' | 'pending' | 'unknown' by inspecting /queue."""
    try:
        import httpx
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{_host()}/queue")
            resp.raise_for_status()
            queue = resp.json()

        running = queue.get("queue_running", [])
        pending = queue.get("queue_pending", [])

        # Each queue entry: [number, prompt_id, workflow, extra_data, ...]
        running_ids = {entry[1] for entry in running if len(entry) > 1}
        pending_ids = {entry[1] for entry in pending if len(entry) > 1}

        if prompt_id in running_ids:
            return "running"
        if prompt_id in pending_ids:
            return "pending"
        return "unknown"

    except Exception:
        return "unknown"


def _extract_outputs(outputs: dict) -> list[dict]:
    """Flatten ComfyUI node outputs into a list of image dicts."""
    results = []
    host = _host()
    for node_id, node_data in outputs.items():
        for img in node_data.get("images", []):
            filename = img.get("filename", "")
            subfolder = img.get("subfolder", "")
            img_type = img.get("type", "output")

            # Build a direct URL to the image via /view endpoint
            params = f"filename={filename}"
            if subfolder:
                params += f"&subfolder={subfolder}"
            params += f"&type={img_type}"

            results.append({
                "node_id": node_id,
                "filename": filename,
                "subfolder": subfolder,
                "type": img_type,
                "url": f"{host}/view?{params}",
            })
    return results
