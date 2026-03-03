function getApiToken() {
  return window.localStorage.getItem("repo_recall_token") || "";
}

function catalogPretty(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

async function catalogFetch(path, options = {}) {
  const token = getApiToken();
  const headers = options.headers ? { ...options.headers } : {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
    headers["X-FF-Token"] = token;
  }
  return fetch(path, { ...options, headers });
}

function v(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

function setMsg(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderSuggestResults(payload) {
  const wrap = document.getElementById("catalogSuggestWrap");
  if (!wrap) return;
  const results = payload && payload.results ? payload.results : [];
  if (!results.length) {
    wrap.innerHTML = `<pre class="pre">${catalogPretty(payload)}</pre>`;
    return;
  }

  let html = `
    <table class="table">
      <thead>
        <tr>
          <th>Repo</th>
          <th>Score</th>
          <th>Freshness</th>
          <th>Reason Codes</th>
          <th>Top Branches</th>
          <th>Repo ID</th>
        </tr>
      </thead>
      <tbody>
  `;
  results.forEach((r) => {
    const repo = r.repo || {};
    const branches = (r.branches || [])
      .map((b) => `${b.name} (${(b.reason_codes || []).join(",")})`)
      .join("<br/>");
    html += `
      <tr>
        <td>${repo.full_name || repo.name || ""}</td>
        <td>${(r.score || 0).toFixed(4)}</td>
        <td>${repo.freshness || ""}</td>
        <td>${(r.reason_codes || []).join(", ")}</td>
        <td>${branches}</td>
        <td><code>${repo.id || ""}</code></td>
      </tr>
    `;
  });
  html += `</tbody></table>`;
  wrap.innerHTML = html;
}

function renderRuns(payload) {
  const wrap = document.getElementById("catalogRunsWrap");
  if (!wrap) return;
  const runs = payload && payload.runs ? payload.runs : [];
  if (!runs.length) {
    wrap.innerHTML = `<div class="muted">No catalog runs yet.</div>`;
    return;
  }
  let html = `
    <table class="table">
      <thead>
        <tr>
          <th>Run ID</th>
          <th>Actor</th>
          <th>Scope</th>
          <th>Status</th>
          <th>Created</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
  `;
  runs.forEach((r) => {
    html += `
      <tr>
        <td><code>${r.id || ""}</code></td>
        <td>${r.actor_id || ""}</td>
        <td>${r.scope || ""}</td>
        <td>${r.status || ""}</td>
        <td>${r.created_at || ""}</td>
        <td>${r.error || ""}</td>
      </tr>
    `;
  });
  html += `</tbody></table>`;
  wrap.innerHTML = html;
}

function renderBranches(payload) {
  const wrap = document.getElementById("catalogBranchesWrap");
  if (!wrap) return;
  const rows = payload && payload.branches ? payload.branches : [];
  if (!rows.length) {
    wrap.innerHTML = `<div class="muted">No branches returned.</div>`;
    return;
  }
  let html = `
    <table class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Default</th>
          <th>Generated</th>
          <th>Protected</th>
          <th>Last Commit</th>
          <th>Head SHA</th>
        </tr>
      </thead>
      <tbody>
  `;
  rows.forEach((b) => {
    html += `
      <tr>
        <td>${b.name || ""}</td>
        <td>${b.is_default ? "yes" : "no"}</td>
        <td>${b.is_generated ? "yes" : "no"}</td>
        <td>${b.protected ? "yes" : "no"}</td>
        <td>${b.last_commit_at || ""}</td>
        <td><code>${b.head_sha || ""}</code></td>
      </tr>
    `;
  });
  html += `</tbody></table>`;
  wrap.innerHTML = html;
}

async function catalogSuggest() {
  const body = {
    actor_id: v("catalogActorId"),
    query: v("catalogQuery"),
    org: v("catalogOrg") || null,
    top_k_repos: parseInt(v("catalogTopRepos") || "5", 10),
    top_k_branches_per_repo: parseInt(v("catalogTopBranches") || "5", 10),
  };
  const token = v("catalogToken");
  if (token) body.github_token = token;
  if (!body.actor_id) {
    setMsg("catalogMsg", "actor_id is required");
    return;
  }

  const resp = await catalogFetch("/api/indexer/catalog/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogMsg", `Suggest failed (${resp.status}): ${txt}`);
    return;
  }
  const payload = JSON.parse(txt);
  setMsg("catalogMsg", payload.auth_required ? `Auth required: ${payload.connect_url}` : "Suggest OK");
  renderSuggestResults(payload);
}

async function catalogSync() {
  const body = {
    actor_id: v("catalogActorId"),
    scope: v("catalogScope") || "incremental",
    org: v("catalogOrg") || null,
    source_token_owner: v("catalogActorId") || null,
    repo_full_name: v("catalogRepoFullName") || null,
  };
  const token = v("catalogToken");
  if (token) body.github_token = token;
  if (!body.actor_id) {
    setMsg("catalogSyncMsg", "actor_id is required");
    return;
  }

  const resp = await catalogFetch("/api/indexer/catalog/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogSyncMsg", `Sync failed (${resp.status}): ${txt}`);
    return;
  }
  const payload = JSON.parse(txt);
  setMsg("catalogSyncMsg", catalogPretty(payload));
}

async function catalogLoadRepos() {
  const actorId = v("catalogActorId");
  if (!actorId) {
    setMsg("catalogMsg", "actor_id is required");
    return;
  }
  const org = v("catalogOrg");
  const query = `/api/indexer/catalog/repos?actor_id=${encodeURIComponent(actorId)}${org ? `&org=${encodeURIComponent(org)}` : ""}`;
  const resp = await catalogFetch(query);
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogMsg", `List repos failed (${resp.status}): ${txt}`);
    return;
  }
  const payload = JSON.parse(txt);
  renderSuggestResults({ results: (payload.repos || []).map((r) => ({ repo: r, score: 0, reason_codes: [], branches: [] })) });
  setMsg("catalogMsg", `Loaded ${payload.repos ? payload.repos.length : 0} repos`);
}

async function catalogLoadBranches() {
  const actorId = v("catalogActorId");
  const repoId = v("catalogRepoIdForBranches");
  if (!actorId || !repoId) {
    setMsg("catalogMsg", "actor_id and repo_id are required");
    return;
  }
  const includeGenerated = document.getElementById("catalogIncludeGenerated").checked;
  const path =
    `/api/indexer/catalog/repos/${encodeURIComponent(repoId)}/branches?actor_id=${encodeURIComponent(actorId)}&include_generated=${includeGenerated ? "true" : "false"}`;
  const resp = await catalogFetch(path);
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogMsg", `Load branches failed (${resp.status}): ${txt}`);
    return;
  }
  renderBranches(JSON.parse(txt));
}

async function catalogLoadRuns() {
  const actorId = v("catalogActorId");
  const path = actorId
    ? `/api/indexer/catalog/runs?actor_id=${encodeURIComponent(actorId)}`
    : "/api/indexer/catalog/runs";
  const resp = await catalogFetch(path);
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogSyncMsg", `Load runs failed (${resp.status}): ${txt}`);
    return;
  }
  renderRuns(JSON.parse(txt));
}

async function catalogStoreActorToken() {
  if (!window.repoRecallCatalogUi || !window.repoRecallCatalogUi.enableDevEndpoints) {
    setMsg("catalogDevMsg", "Dev endpoints are disabled.");
    return;
  }
  const actorId = v("catalogActorId");
  const token = v("catalogToken");
  const ttl = parseInt(v("catalogTokenTtl") || "3600", 10);
  if (!actorId || !token) {
    setMsg("catalogDevMsg", "actor_id and token are required");
    return;
  }
  const resp = await catalogFetch("/api/indexer/catalog/dev/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: actorId, github_token: token, ttl_seconds: ttl }),
  });
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogDevMsg", `Store token failed (${resp.status}): ${txt}`);
    return;
  }
  setMsg("catalogDevMsg", txt);
}

async function catalogSeedDemo() {
  if (!window.repoRecallCatalogUi || !window.repoRecallCatalogUi.enableDevEndpoints) {
    setMsg("catalogDevMsg", "Dev endpoints are disabled.");
    return;
  }
  const actorId = v("catalogActorId");
  const org = v("catalogOrg") || "demo-org";
  if (!actorId) {
    setMsg("catalogDevMsg", "actor_id is required");
    return;
  }
  const resp = await catalogFetch("/api/indexer/catalog/dev/seed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: actorId, org }),
  });
  const txt = await resp.text();
  if (!resp.ok) {
    setMsg("catalogDevMsg", `Seed failed (${resp.status}): ${txt}`);
    return;
  }
  setMsg("catalogDevMsg", txt);
}

function initCatalogUi() {
  const suggestBtn = document.getElementById("catalogSuggestBtn");
  if (!suggestBtn) return;
  suggestBtn.addEventListener("click", catalogSuggest);
  document.getElementById("catalogSyncBtn").addEventListener("click", catalogSync);
  document.getElementById("catalogListReposBtn").addEventListener("click", catalogLoadRepos);
  document.getElementById("catalogBranchesBtn").addEventListener("click", catalogLoadBranches);
  document.getElementById("catalogRunsBtn").addEventListener("click", catalogLoadRuns);
  document.getElementById("catalogStoreTokenBtn").addEventListener("click", catalogStoreActorToken);
  document.getElementById("catalogSeedBtn").addEventListener("click", catalogSeedDemo);
}

window.addEventListener("DOMContentLoaded", initCatalogUi);
