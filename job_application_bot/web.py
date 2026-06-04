"""Local web UI for generating tailored application artifacts from a job link."""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from config.settings import OUTPUT_DIR, PROJECT_ROOT


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Application Bot</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17202a;
      --muted: #5a6473;
      --line: #d9dee7;
      --panel: #ffffff;
      --page: #f4f6f8;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --danger: #b42318;
      --ok: #067647;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--page);
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
    }
    aside {
      background: #111827;
      color: #f9fafb;
      padding: 28px 22px;
    }
    .brand {
      font-size: 18px;
      font-weight: 760;
      letter-spacing: 0;
      margin-bottom: 22px;
    }
    .nav-item {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,0.12);
      color: #d1d5db;
      font-size: 13px;
    }
    .nav-item strong { color: #fff; font-weight: 650; }
    main { padding: 30px; }
    .topbar {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 18px;
    }
    h1 {
      margin: 0;
      font-size: 26px;
      line-height: 1.15;
      letter-spacing: 0;
    }
    .sub {
      color: var(--muted);
      margin-top: 6px;
      font-size: 14px;
    }
    .status-pill {
      min-width: 138px;
      text-align: center;
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 650;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 18px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 7px;
    }
    input, textarea {
      width: 100%;
      border: 1px solid #c9d2df;
      border-radius: 6px;
      padding: 11px 12px;
      font: inherit;
      font-size: 14px;
      color: var(--ink);
      background: #fff;
    }
    textarea {
      min-height: 180px;
      resize: vertical;
      line-height: 1.4;
    }
    .row { margin-bottom: 14px; }
    .actions {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      background: var(--accent);
      color: #fff;
      font-weight: 740;
      cursor: pointer;
      min-height: 40px;
    }
    button.secondary {
      background: #e8eef5;
      color: #1f2937;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.65;
    }
    .hint, .small {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .metric {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
      font-size: 13px;
    }
    .metric:last-child { border-bottom: 0; }
    .metric span { color: var(--muted); }
    .metric strong { text-align: right; }
    .links {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .links a {
      display: block;
      color: var(--accent-strong);
      text-decoration: none;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font-size: 13px;
      background: #fbfcfd;
      word-break: break-word;
    }
    .links a:hover { border-color: var(--accent); }
    .error {
      color: var(--danger);
      background: #fff4f2;
      border: 1px solid #f3b8b0;
      border-radius: 6px;
      padding: 10px 12px;
      font-size: 13px;
      margin-top: 12px;
      display: none;
    }
    .log {
      white-space: pre-wrap;
      overflow: auto;
      max-height: 240px;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      line-height: 1.45;
      color: #374151;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      margin-top: 12px;
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; }
      aside { padding: 18px; }
      main { padding: 18px; }
      .grid { grid-template-columns: 1fr; }
      .topbar { align-items: stretch; flex-direction: column; }
      .status-pill { text-align: left; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">Job Application Bot</div>
      <div class="nav-item"><span>Input</span><strong>Job URL</strong></div>
      <div class="nav-item"><span>Backend</span><strong>Existing pipeline</strong></div>
      <div class="nav-item"><span>Output</span><strong>Resume artifacts</strong></div>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h1>Generate ATS Resume From a Job Link</h1>
          <div class="sub">Paste the posting URL here and the current backend will extract the JD, tailor the resume, score it, and save artifacts.</div>
        </div>
        <div class="status-pill" id="status">Ready</div>
      </div>
      <div class="grid">
        <section class="panel">
          <form id="applicationForm">
            <div class="row">
              <label for="jobUrl">Job posting URL</label>
              <input id="jobUrl" name="jobUrl" type="url" placeholder="https://jobs.example.com/role/123" autocomplete="off">
            </div>
            <div class="row">
              <label for="jdText">Optional full JD text</label>
              <textarea id="jdText" name="jdText" placeholder="Use this when LinkedIn or another site blocks extraction."></textarea>
              <div class="hint">If JD text is provided, the backend uses it directly and keeps the URL as source context.</div>
            </div>
            <div class="actions">
              <button id="submitBtn" type="submit">Generate Resume</button>
              <button class="secondary" type="button" id="clearBtn">Clear</button>
              <span class="small">Long runs can take a few minutes.</span>
            </div>
          </form>
          <div class="error" id="error"></div>
          <div class="log" id="log">No run yet.</div>
        </section>
        <aside class="panel">
          <div class="metric"><span>Company</span><strong id="company">-</strong></div>
          <div class="metric"><span>ATS Score</span><strong id="ats">-</strong></div>
          <div class="metric"><span>Duration</span><strong id="duration">-</strong></div>
          <div class="metric"><span>Status</span><strong id="resultStatus">Waiting</strong></div>
          <div class="links" id="links"></div>
        </aside>
      </div>
    </main>
  </div>
  <script>
    const form = document.getElementById('applicationForm');
    const submitBtn = document.getElementById('submitBtn');
    const clearBtn = document.getElementById('clearBtn');
    const statusEl = document.getElementById('status');
    const errorEl = document.getElementById('error');
    const logEl = document.getElementById('log');
    const linksEl = document.getElementById('links');
    const companyEl = document.getElementById('company');
    const atsEl = document.getElementById('ats');
    const durationEl = document.getElementById('duration');
    const resultStatusEl = document.getElementById('resultStatus');

    function setBusy(isBusy) {
      submitBtn.disabled = isBusy;
      statusEl.textContent = isBusy ? 'Running' : 'Ready';
    }

    function showError(message) {
      errorEl.textContent = message;
      errorEl.style.display = message ? 'block' : 'none';
    }

    function resetResults() {
      companyEl.textContent = '-';
      atsEl.textContent = '-';
      durationEl.textContent = '-';
      resultStatusEl.textContent = 'Waiting';
      linksEl.innerHTML = '';
      logEl.textContent = 'No run yet.';
      showError('');
    }

    clearBtn.addEventListener('click', () => {
      form.reset();
      resetResults();
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      showError('');
      linksEl.innerHTML = '';
      resultStatusEl.textContent = 'Running';
      logEl.textContent = 'Starting backend pipeline...';
      setBusy(true);

      const payload = {
        job_url: document.getElementById('jobUrl').value.trim(),
        jd_text: document.getElementById('jdText').value.trim()
      };

      try {
        const response = await fetch('/api/applications', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.error || 'Pipeline failed');
        }

        companyEl.textContent = data.company || '-';
        atsEl.textContent = data.ats_score == null ? '-' : `${data.ats_score}/100`;
        durationEl.textContent = data.duration_seconds == null ? '-' : `${data.duration_seconds.toFixed(1)}s`;
        resultStatusEl.textContent = 'Complete';
        logEl.textContent = data.message || 'Run complete.';

        for (const artifact of data.artifacts || []) {
          const link = document.createElement('a');
          link.href = artifact.url;
          link.textContent = artifact.label;
          link.target = '_blank';
          link.rel = 'noopener';
          linksEl.appendChild(link);
        }
      } catch (error) {
        resultStatusEl.textContent = 'Failed';
        logEl.textContent = 'The backend returned an error.';
        showError(error.message);
      } finally {
        setBusy(false);
      }
    });
  </script>
</body>
</html>
"""


ARTIFACT_LABELS = {
    "resume_path": "Resume PDF",
    "markdown_resume_path": "Markdown Resume",
    "cover_letter_path": "Cover Letter",
    "jd_text_path": "Job Description Text",
}


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: int, content: str, content_type: str) -> None:
    body = content.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_output_file(relative_path: str) -> Path | None:
    output_root = OUTPUT_DIR.resolve()
    target = (output_root / relative_path).resolve()
    if output_root == target or output_root in target.parents:
        return target
    return None


def _artifact_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value).resolve()
    try:
        relative = path.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return None
    return "/artifacts/" + relative.as_posix()


def _company_from_output_dir(output_dir: str | None) -> str:
    if not output_dir:
        return ""
    name = Path(output_dir).name
    parts = name.split("_")
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
        return "_".join(parts[:-2]) or name
    if len(parts) >= 2 and parts[-1].isdigit():
        return "_".join(parts[:-1]) or name
    return name


def _result_payload(result: Any) -> dict[str, Any]:
    artifacts = []
    for attr, label in ARTIFACT_LABELS.items():
        path_value = getattr(result, attr, None)
        url = _artifact_url(path_value)
        if url:
            artifacts.append({"label": label, "url": url, "path": path_value})

    return {
        "success": not bool(getattr(result, "error", None)),
        "error": getattr(result, "error", None),
        "message": "Generated resume artifacts from the current backend pipeline.",
        "job_url": getattr(result, "job_url", ""),
        "company": _company_from_output_dir(getattr(result, "output_dir", None)),
        "output_dir": getattr(result, "output_dir", None),
        "ats_score": getattr(result, "ats_score", None),
        "duration_seconds": getattr(result, "duration_seconds", None),
        "artifacts": artifacts,
    }


async def run_application_pipeline(job_url: str, jd_text: str | None) -> Any:
    from main import orchestrate_application

    return await orchestrate_application(
        job_url=job_url,
        manual_jd_text=jd_text or None,
        manual_jd_source="web form JD text" if jd_text else None,
        skip_apply=True,
        dry_run=True,
    )


class JobApplicationWebHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local web UI."""

    server_version = "JobApplicationBotWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[web] " + format % args + "\n")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            _text_response(self, 200, INDEX_HTML, "text/html; charset=utf-8")
            return

        if parsed.path == "/api/health":
            _json_response(self, 200, {"ok": True, "project_root": str(PROJECT_ROOT)})
            return

        if parsed.path.startswith("/artifacts/"):
            relative = unquote(parsed.path.removeprefix("/artifacts/"))
            target = _safe_output_file(relative)
            if not target or not target.exists() or not target.is_file():
                _json_response(self, 404, {"success": False, "error": "Artifact not found"})
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
            self.end_headers()
            self.wfile.write(body)
            return

        _json_response(self, 404, {"success": False, "error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/applications":
            _json_response(self, 404, {"success": False, "error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            job_url = str(payload.get("job_url") or "").strip()
            jd_text = str(payload.get("jd_text") or "").strip()

            if not job_url and not jd_text:
                _json_response(
                    self,
                    400,
                    {"success": False, "error": "Provide a job URL or paste the full JD text."},
                )
                return

            result = asyncio.run(run_application_pipeline(job_url, jd_text or None))
            payload = _result_payload(result)
            _json_response(self, 200 if payload["success"] else 500, payload)
        except Exception as exc:
            _json_response(
                self,
                500,
                {
                    "success": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Job Application Bot website.")
    parser.add_argument("--host", default=os.getenv("JOB_BOT_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("JOB_BOT_WEB_PORT", "8765")))
    parser.add_argument("--log-file", default=os.getenv("JOB_BOT_WEB_LOG_FILE", ""))
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
        sys.stdout = log_file
        sys.stderr = log_file
    server = ThreadingHTTPServer((args.host, args.port), JobApplicationWebHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Job Application Bot website running at {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
