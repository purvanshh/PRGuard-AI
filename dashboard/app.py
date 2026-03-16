"""Simple FastAPI dashboard for PRGuard AI traces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from observability.logging import fetch_pr_logs


app = FastAPI(title="PRGuard AI Dashboard", version="0.1.0")


def _render_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
      h1, h2, h3 {{ color: #222; }}
      .card {{ border: 1px solid #ddd; border-radius: 6px; padding: 1rem; margin-bottom: 1rem; }}
      .badge {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 4px; background: #eee; margin-right: 0.25rem; font-size: 0.8rem; }}
      .agent-name {{ font-weight: bold; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
      th {{ background: #f5f5f5; }}
    </style>
  </head>
  <body>
    {body}
  </body>
</html>
"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index() -> str:
    body = "<h1>PRGuard AI Dashboard</h1>"
    body += "<p>Use <code>/review/&lt;pr_id&gt;</code> to inspect a specific pull request trace.</p>"
    return _render_html("PRGuard AI Dashboard", body)


@app.get("/review/{pr_id}", response_class=HTMLResponse)
async def review_detail(pr_id: str) -> str:
    logs = fetch_pr_logs(pr_id)
    if not logs:
        raise HTTPException(status_code=404, detail="No logs found for PR")

    body = f"<h1>Review Trace for {pr_id}</h1>"
    body += "<div class='card'><h2>Execution Timeline</h2>"
    body += "<table><tr><th>Order</th><th>Agent</th><th>Started</th><th>Finished</th><th>Duration (s)</th><th>Confidence</th></tr>"
    for entry in logs:
        body += "<tr>"
        body += f"<td>{entry.get('agent_order', '')}</td>"
        body += f"<td>{entry['agent']}</td>"
        body += f"<td>{entry['started_at']:.3f}</td>"
        body += f"<td>{entry['finished_at']:.3f}</td>"
        body += f"<td>{(entry.get('execution_duration') or 0):.3f}</td>"
        body += f"<td>{(entry.get('confidence') or 0):.2f}</td>"
        body += "</tr>"
    body += "</table></div>"

    body += "<div class='card'><h2>Agent Outputs</h2>"
    for entry in logs:
        agent = entry["agent"]
        output: Dict[str, Any] = entry.get("output") or {}
        issues: List[Dict[str, Any]] = [
            i if isinstance(i, dict) else {}
            for i in (output.get("issues") or [])
        ]
        body += f"<h3>{agent}</h3>"
        if not issues:
            body += "<p><em>No issues reported.</em></p>"
            continue
        body += "<ul>"
        for issue in issues:
            body += "<li>"
            body += f"<span class='badge'>{issue.get('severity', '').upper()}</span>"
            if issue.get("file_path"):
                body += f"<span class='badge'>{issue['file_path']}:{issue.get('line')}</span>"
            body += f"{issue.get('message')}"
            body += "</li>"
        body += "</ul>"
    body += "</div>"
    body += f"<p><a href='/live/{pr_id}'>View live agent visualization for this PR</a></p>"

    return _render_html(f"Review {pr_id}", body)


@app.get("/live/{pr_id}", response_class=HTMLResponse)
async def live_view(pr_id: str) -> str:
    """
    Live agent visualization page backed by the /stream/{pr_id} WebSocket.
    """
    body = f"""
<h1>Live Agent Execution for {pr_id}</h1>
<div class="card">
  <h2>Status</h2>
  <pre id="log"></pre>
</div>
<div class="card">
  <h2>Confidence</h2>
  <p>Overall confidence: <span id="confidence">n/a</span></p>
</div>
<script>
  const logEl = document.getElementById("log");
  const confEl = document.getElementById("confidence");
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/stream/{pr_id}");

  ws.onmessage = (event) => {{
    const data = JSON.parse(event.data);
    const line = JSON.stringify(data);
    logEl.textContent += line + "\\n";
    if (data.type === "confidence_updated" && data.overall_confidence !== undefined) {{
      confEl.textContent = data.overall_confidence.toFixed(2);
    }}
  }};

  ws.onopen = () => {{
    logEl.textContent += "Connected to live stream...\\n";
  }};

  ws.onclose = () => {{
    logEl.textContent += "Disconnected from live stream.\\n";
  }};
</script>
"""
    return _render_html(f"Live {pr_id}", body)


__all__ = ["app"]

