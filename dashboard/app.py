"""Simple FastAPI dashboard for PRGuard AI traces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from observability.logging import fetch_pr_logs
from evaluation.evaluator import evaluate_pr


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
      .timeline-bar {{ height: 1rem; background: #4f46e5; border-radius: 4px; }}
      .timeline-row {{ margin-bottom: 0.5rem; }}
      .timeline-label {{ display: inline-block; width: 120px; }}
      .issue-list {{ max-height: 200px; overflow-y: auto; }}
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

    # Agent timeline visualization.
    if logs:
        first_start = min(e["started_at"] for e in logs)
        last_end = max(e["finished_at"] for e in logs)
        total_span = max(last_end - first_start, 1e-6)
        body += "<div class='card'><h2>Agent Timeline</h2>"
        for entry in logs:
            start_offset = entry["started_at"] - first_start
            duration = (entry.get("execution_duration") or 0.0)
            start_pct = max(start_offset / total_span * 100.0, 0.0)
            width_pct = max(duration / total_span * 100.0, 2.0)
            body += "<div class='timeline-row'>"
            body += f"<span class='timeline-label'>{entry['agent']}</span>"
            body += "<div style='display:inline-block; width:60%; position:relative; height:1rem; background:#f3f4f6; border-radius:4px;'>"
            body += f"<div class='timeline-bar' style='position:absolute; left:{start_pct:.1f}%; width:{width_pct:.1f}%;'></div>"
            body += "</div>"
            body += "</div>"
        body += "</div>"

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


@app.get("/demo", response_class=HTMLResponse)
async def demo_page() -> str:
    """
    Simple demo page for trying out live streaming with a PR ID.
    """
    body = """
<h1>PRGuard AI Live Demo</h1>
<div class="card">
  <h2>Simulate PR Analysis</h2>
  <p>Enter a PR ID (e.g. <code>owner/repo#123</code>) that is being analyzed by PRGuard AI,
  then click <strong>Connect</strong> to watch live agent events.</p>
  <label>GitHub Repository URL: <input id="repo_url" type="text" style="width: 60%%;" placeholder="https://github.com/owner/repo"></label><br/><br/>
  <label>PR ID: <input id="pr_id" type="text" style="width: 40%%;" placeholder="owner/repo#123"></label>
  <button onclick="connectDemo()">Connect</button>
</div>
<div class="card">
  <h2>Live Events</h2>
  <pre id="demo_log"></pre>
</div>
<div class="card">
  <h2>Current Status</h2>
  <p>Overall confidence: <span id="demo_conf">n/a</span></p>
  <div class="issue-list">
    <ul id="demo_issues"></ul>
  </div>
</div>
<script>
  let ws = null;
  function connectDemo() {
    const prInput = document.getElementById("pr_id");
    const prId = prInput.value.trim();
    if (!prId) {
      alert("Please enter a PR ID.");
      return;
    }
    const logEl = document.getElementById("demo_log");
    const confEl = document.getElementById("demo_conf");
    const issuesEl = document.getElementById("demo_issues");
    logEl.textContent = "";
    issuesEl.innerHTML = "";
    if (ws) {
      ws.close();
    }
    const encodedPrId = encodeURIComponent(prId);
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/stream/" + encodedPrId);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      logEl.textContent += JSON.stringify(data) + "\\n";
      if (data.type === "confidence_updated" && data.overall_confidence !== undefined) {
        confEl.textContent = data.overall_confidence.toFixed(2);
      }
      if (data.type === "agent_finished" && data.issue_count !== undefined) {
        const li = document.createElement("li");
        li.textContent = data.agent + " finished with " + data.issue_count + " issues (confidence " + data.confidence.toFixed(2) + ")";
        issuesEl.appendChild(li);
      }
    };
    ws.onopen = () => {
      logEl.textContent += "Connected to live stream for " + prId + "...\\n";
    };
    ws.onclose = () => {
      logEl.textContent += "Disconnected from live stream.\\n";
    };
  }
</script>
"""
    return _render_html("PRGuard Demo", body)


@app.get("/dataset", response_class=HTMLResponse)
async def dataset_index() -> str:
    """
    Simple browser for evaluation dataset samples.
    """
    dataset_dir = Path("evaluation/dataset")
    samples = sorted(dataset_dir.glob("*.json"))
    body = "<h1>Evaluation Dataset</h1>"
    body += "<div class='card'><ul>"
    for sample in samples:
        name = sample.name
        body += f"<li><a href='/dataset/{name}'>{name}</a></li>"
    body += "</ul></div>"
    return _render_html("Dataset", body)


@app.get("/dataset/{sample_name}", response_class=HTMLResponse)
async def dataset_detail(sample_name: str) -> str:
    dataset_dir = Path("evaluation/dataset")
    sample_path = dataset_dir / sample_name
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail="Sample not found")
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    diff = data.get("diff", "")
    expected = data.get("expected_issues", [])

    body = f"<h1>Dataset Sample: {sample_name}</h1>"
    body += "<div class='card'><h2>Description</h2>"
    body += f"<p>{data.get('description','(no description)')}</p></div>"

    body += "<div class='card'><h2>Diff</h2><pre>{}</pre></div>".format(diff.replace("<", "&lt;").replace(">", "&gt;"))

    body += "<div class='card'><h2>Expected Issues</h2><ul>"
    for issue in expected:
        body += f"<li>Line {issue.get('line')}: {issue.get('message')}</li>"
    body += "</ul></div>"

    # Provide a link that runs the evaluation and shows metrics.
    body += f"<p><a href='/dataset/{sample_name}/run'>Run analysis on this sample</a></p>"
    return _render_html(f"Dataset {sample_name}", body)


@app.get("/dataset/{sample_name}/run", response_class=HTMLResponse)
async def dataset_run(sample_name: str) -> str:
    dataset_dir = Path("evaluation/dataset")
    sample_path = dataset_dir / sample_name
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail="Sample not found")
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    diff = data.get("diff", "")
    expected = data.get("expected_issues", [])
    metrics = evaluate_pr(diff, expected)

    body = f"<h1>Run Result: {sample_name}</h1>"
    body += "<div class='card'><h2>Metrics</h2><ul>"
    for k in ["true_positive", "false_positive", "missed_issue", "precision", "recall", "confidence"]:
        body += f"<li>{k}: {metrics.get(k)}</li>"
    body += "</ul></div>"
    return _render_html(f"Run {sample_name}", body)


__all__ = ["app"]

