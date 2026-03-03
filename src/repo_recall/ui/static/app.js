function getToken() {
  return window.localStorage.getItem("repo_recall_token") || "";
}

function setToken(token) {
  if (token) {
    window.localStorage.setItem("repo_recall_token", token);
  } else {
    window.localStorage.removeItem("repo_recall_token");
  }
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = options.headers ? { ...options.headers } : {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
    headers["X-FF-Token"] = token;
  }
  return fetch(path, { ...options, headers });
}

function pretty(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = "block";
  el.textContent = msg;
}

function clearError(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = "none";
  el.textContent = "";
}

async function refreshStatus() {
  const healthEl = document.getElementById("health");
  const readyEl = document.getElementById("ready");
  const runtimeEl = document.getElementById("runtime");
  const statsEl = document.getElementById("stats");

  try {
    const h = await apiFetch("/health");
    healthEl.textContent = pretty(await h.json());
  } catch (e) {
    healthEl.textContent = `Error: ${e}`;
  }

  try {
    const r = await apiFetch("/health/ready");
    readyEl.textContent = pretty(await r.json());
  } catch (e) {
    readyEl.textContent = `Error: ${e}`;
  }

  try {
    const rt = await apiFetch("/health/runtime");
    runtimeEl.textContent = pretty(await rt.json());
  } catch (e) {
    runtimeEl.textContent = `Error: ${e}`;
  }

  try {
    const s = await apiFetch("/api/indexer/stats");
    statsEl.textContent = pretty(await s.json());
  } catch (e) {
    statsEl.textContent = `Error: ${e}`;
  }
}

function renderResults(payload) {
  const wrap = document.getElementById("searchResults");
  wrap.innerHTML = "";

  if (!payload || !payload.results || payload.results.length === 0) {
    wrap.innerHTML = '<div class="muted">No results</div>';
    return;
  }

  payload.results.forEach((r, idx) => {
    const repo = r.repo || {};
    const div = document.createElement("div");
    div.className = "result";

    const title = document.createElement("h3");
    title.textContent = `#${idx + 1} ${repo.name || "(unknown repo)"}`;

    const meta = document.createElement("div");
    meta.innerHTML = `
      <div class="kv">
        <div class="k">Score</div><div>${(r.score || 0).toFixed(4)}</div>
        <div class="k">Source</div><div>${repo.source || ""}:${repo.source_ref || ""}</div>
        <div class="k">Branch</div><div>${repo.default_branch || ""}</div>
        <div class="k">Indexed</div><div>${repo.indexed_at || ""}</div>
        <div class="k">Commit</div><div>${repo.indexed_commit_sha || ""}</div>
      </div>
    `;

    div.appendChild(title);
    div.appendChild(meta);

    const ev = r.evidence || [];
    if (ev.length > 0) {
      const table = document.createElement("table");
      table.className = "table";
      table.innerHTML = `
        <thead>
          <tr>
            <th>File</th>
            <th>Lines</th>
            <th>Type</th>
            <th>Score</th>
            <th>Snippet</th>
          </tr>
        </thead>
        <tbody>
        </tbody>
      `;
      const tbody = table.querySelector("tbody");
      ev.forEach((c) => {
        const tr = document.createElement("tr");
        const lines = (c.start_line != null && c.end_line != null) ? `${c.start_line}-${c.end_line}` : "";
        const snippet = (c.text || "").replace(/\n/g, " ").slice(0, 260);
        tr.innerHTML = `
          <td><span class="badge">${c.file_path}</span></td>
          <td>${lines}</td>
          <td>${c.content_type}</td>
          <td>${(c.score || 0).toFixed(4)}</td>
          <td>${snippet}${(c.text || "").length > 260 ? "…" : ""}</td>
        `;
        tbody.appendChild(tr);
      });
      div.appendChild(table);
    }

    wrap.appendChild(div);
  });
}

async function runSearch() {
  clearError("searchError");
  const q = document.getElementById("queryInput").value.trim();
  const topKRepos = parseInt(document.getElementById("topKRepos").value || "5", 10);
  const topKChunks = parseInt(document.getElementById("topKChunks").value || "3", 10);

  if (!q) {
    showError("searchError", "Enter a query.");
    return;
  }

  const resp = await apiFetch("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: q, top_k_repos: topKRepos, top_k_chunks: topKChunks }),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    showError("searchError", `Search failed (${resp.status}): ${txt}`);
    return;
  }

  const payload = await resp.json();
  renderResults(payload);
}

function renderReposTable(rows) {
  const wrap = document.getElementById("reposTableWrap");
  if (!rows || rows.length === 0) {
    wrap.innerHTML = '<div class="muted">No repos indexed yet.</div>';
    return;
  }

  let html = `
    <table class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Source</th>
          <th>Branch</th>
          <th>Indexed at</th>
          <th>Commit</th>
        </tr>
      </thead>
      <tbody>
  `;

  rows.forEach((r) => {
    html += `
      <tr>
        <td>${r.name || ""}</td>
        <td>${r.source || ""}:${r.source_ref || ""}</td>
        <td>${r.default_branch || ""}</td>
        <td>${r.indexed_at || ""}</td>
        <td>${r.indexed_commit_sha || ""}</td>
      </tr>
    `;
  });

  html += `</tbody></table>`;
  wrap.innerHTML = html;
}

async function refreshRepos() {
  const resp = await apiFetch("/api/indexer/repos?limit=50");
  if (!resp.ok) {
    const txt = await resp.text();
    document.getElementById("reposTableWrap").innerHTML = `<div class="error">Failed: ${txt}</div>`;
    return;
  }
  const payload = await resp.json();
  renderReposTable(payload.repos || []);
}

function renderRunsTable(rows) {
  const wrap = document.getElementById("runsTableWrap");
  if (!rows || rows.length === 0) {
    wrap.innerHTML = '<div class="muted">No runs yet.</div>';
    return;
  }

  let html = `
    <table class="table">
      <thead>
        <tr>
          <th>Run ID</th>
          <th>Status</th>
          <th>Operation</th>
          <th>Repo</th>
          <th>Created</th>
          <th>Started</th>
          <th>Finished</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
  `;

  rows.forEach((r) => {
    html += `
      <tr>
        <td><code>${r.id}</code></td>
        <td>${r.status}</td>
        <td>${r.operation}</td>
        <td>${r.repo_ref || ""}</td>
        <td>${r.created_at || ""}</td>
        <td>${r.started_at || ""}</td>
        <td>${r.finished_at || ""}</td>
        <td>${r.error || ""}</td>
      </tr>
    `;
  });

  html += `</tbody></table>`;
  wrap.innerHTML = html;
}

async function refreshRuns() {
  const resp = await apiFetch("/api/indexer/runs?limit=25");
  if (!resp.ok) {
    const txt = await resp.text();
    document.getElementById("runsTableWrap").innerHTML = `<div class="error">Failed: ${txt}</div>`;
    return;
  }
  const payload = await resp.json();
  renderRunsTable(payload.runs || []);
}

async function pollRun(runId, maxAttempts = 30) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const resp = await apiFetch(`/api/indexer/runs/${runId}`);
    if (!resp.ok) continue;
    const payload = await resp.json();
    const st = payload.run && payload.run.status;
    if (st === "succeeded" || st === "failed") {
      return payload;
    }
  }
  return null;
}

async function runIndex() {
  const repoRef = document.getElementById("repoRefInput").value.trim();
  const incremental = document.getElementById("incremental").checked;
  const msg = document.getElementById("indexMsg");
  msg.textContent = "";

  if (!repoRef) {
    msg.textContent = "Enter a repo path or git URL.";
    return;
  }

  const resp = await apiFetch("/api/indexer/index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo: repoRef, incremental }),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    msg.textContent = `Index request failed (${resp.status}): ${txt}`;
    return;
  }

  const payload = await resp.json();
  msg.textContent = `Queued run_id=${payload.run_id}. Polling…`;
  await refreshRuns();

  const done = await pollRun(payload.run_id);
  await refreshRuns();
  await refreshRepos();
  await refreshStatus();

  if (done && done.run) {
    msg.textContent = `Run ${done.run.status}.`;
    if (done.run.error) {
      msg.textContent += ` Error: ${done.run.error}`;
    }
  } else {
    msg.textContent = `Queued run_id=${payload.run_id}. Check the Index Runs table for status.`;
  }
}

function init() {
  // token controls
  const tokenInput = document.getElementById("tokenInput");
  tokenInput.value = getToken();

  document.getElementById("saveToken").addEventListener("click", () => {
    setToken(tokenInput.value.trim());
    refreshStatus();
  });

  document.getElementById("clearToken").addEventListener("click", () => {
    tokenInput.value = "";
    setToken("");
    refreshStatus();
  });

  // buttons
  document.getElementById("runSearch").addEventListener("click", runSearch);
  document.getElementById("refreshRepos").addEventListener("click", refreshRepos);
  document.getElementById("refreshRuns").addEventListener("click", refreshRuns);
  document.getElementById("runIndex").addEventListener("click", runIndex);

  // enter-to-search
  document.getElementById("queryInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });

  refreshStatus();
  refreshRepos();
  refreshRuns();
}

window.addEventListener("DOMContentLoaded", init);
