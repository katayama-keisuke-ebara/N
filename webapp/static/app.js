function getCookie(name) {
  const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

async function apiFetch(url, options = {}) {
  const opts = Object.assign({credentials: "same-origin"}, options);
  opts.headers = Object.assign({}, options.headers || {});
  const method = (opts.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    opts.headers["X-CSRF-Token"] = getCookie("csrf_token") || "";
  }
  const res = await fetch(url, opts);
  if (res.status === 401) {
    window.location.href = "login";
    throw new Error("unauthorized");
  }
  return res;
}

let selectedFiles = [];
let currentJobId = null;
let currentResults = [];
let currentCandidates = [];
let currentCandidateIndex = 0;

async function init() {
  const me = await apiFetch("auth/me");
  if (me.ok) {
    const data = await me.json();
    document.getElementById("username-label").textContent = data.username;
  }

  const configRes = await apiFetch("api/config");
  if (configRes.ok) {
    const config = await configRes.json();
    document.getElementById("sheet_w").value = config.sheet_w;
    document.getElementById("sheet_h").value = config.sheet_h;
    document.getElementById("thickness").value = config.thickness;
    document.getElementById("clearance").value = config.clearance;
  }

  document.getElementById("file-input").addEventListener("change", onFilesSelected);
  document.getElementById("run-btn").addEventListener("click", onRun);
  document.getElementById("logout-btn").addEventListener("click", onLogout);
  document.getElementById("download-zip-btn").addEventListener("click", onDownloadZip);
}

function onFilesSelected(e) {
  selectedFiles = Array.from(e.target.files);
  const tbody = document.querySelector("#parts-table tbody");
  tbody.innerHTML = "";
  selectedFiles.forEach((file, i) => {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td");
    nameTd.textContent = file.name;
    const qtyTd = document.createElement("td");
    const qtyInput = document.createElement("input");
    qtyInput.type = "number";
    qtyInput.title = "0または負数で自動計算(最大取り数)";
    qtyInput.value = "1";
    qtyInput.dataset.index = i;
    qtyTd.appendChild(qtyInput);
    tr.appendChild(nameTd);
    tr.appendChild(qtyTd);
    tbody.appendChild(tr);
  });
}

async function onRun() {
  const errorText = document.getElementById("error-text");
  const statusText = document.getElementById("status-text");
  errorText.textContent = "";
  if (selectedFiles.length === 0) {
    errorText.textContent = "STEP ファイルを選択してください";
    return;
  }

  const sheet_w = parseFloat(document.getElementById("sheet_w").value);
  const sheet_h = parseFloat(document.getElementById("sheet_h").value);
  const thickness = parseFloat(document.getElementById("thickness").value);
  const clearance = parseFloat(document.getElementById("clearance").value);

  document.getElementById("run-btn").disabled = true;
  statusText.textContent = "アップロード中…";

  try {
    const formData = new FormData();
    selectedFiles.forEach((f) => formData.append("files", f));
    const uploadRes = await apiFetch("api/uploads", {method: "POST", body: formData});
    if (!uploadRes.ok) {
      const data = await uploadRes.json().catch(() => ({}));
      throw new Error(data.detail || "アップロードに失敗しました");
    }
    const uploadData = await uploadRes.json();

    const qtyInputs = document.querySelectorAll("#parts-table tbody input[type=number]");
    const parts = uploadData.uploads.map((u, i) => {
      const parsed = parseInt(qtyInputs[i].value, 10);
      return {upload_id: u.upload_id, quantity: Number.isNaN(parsed) ? 1 : parsed};
    });

    const jobRes = await apiFetch("api/jobs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({parts, sheet_w, sheet_h, thickness, clearance}),
    });
    if (!jobRes.ok) {
      const data = await jobRes.json().catch(() => ({}));
      throw new Error(data.detail || "ジョブの作成に失敗しました");
    }
    const jobData = await jobRes.json();
    currentJobId = jobData.job_id;

    await apiFetch("api/config", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({parts: [], sheet_w, sheet_h, thickness, clearance}),
    });

    pollJob();
  } catch (err) {
    errorText.textContent = err.message;
    document.getElementById("run-btn").disabled = false;
    statusText.textContent = "";
  }
}

async function pollJob() {
  const statusText = document.getElementById("status-text");
  const errorText = document.getElementById("error-text");
  const res = await apiFetch(`api/jobs/${currentJobId}`);
  const data = await res.json();
  statusText.textContent = data.progress || data.status;

  if (data.status === "done") {
    document.getElementById("run-btn").disabled = false;
    await loadResults();
  } else if (data.status === "error") {
    document.getElementById("run-btn").disabled = false;
    errorText.textContent = data.error || "処理に失敗しました";
  } else {
    setTimeout(pollJob, 1500);
  }
}

async function loadResults() {
  const res = await apiFetch(`api/jobs/${currentJobId}/candidates`);
  const data = await res.json();
  currentResults = data.results;
  currentCandidates = data.candidates;
  currentCandidateIndex = 0;

  document.getElementById("results-panel").hidden = false;
  renderTabs();
  renderCandidate();
}

function renderTabs() {
  const tabsDiv = document.getElementById("candidate-tabs");
  tabsDiv.innerHTML = "";
  currentCandidates.forEach((c, i) => {
    const btn = document.createElement("button");
    btn.className = "tab" + (i === currentCandidateIndex ? " active" : "");
    btn.textContent = `案${i + 1} (歩留まり ${c.yield_pct.toFixed(1)}%)`;
    btn.addEventListener("click", () => {
      currentCandidateIndex = i;
      renderTabs();
      renderCandidate();
    });
    tabsDiv.appendChild(btn);
  });
}

function renderCandidate() {
  const candidate = currentCandidates[currentCandidateIndex];
  document.getElementById("nesting-image").src =
    `api/jobs/${currentJobId}/render?candidate=${currentCandidateIndex}&t=${Date.now()}`;

  const tbody = document.querySelector("#breakdown-table tbody");
  tbody.innerHTML = "";
  currentResults.forEach((r, i) => {
    const partId = r.part_id || `${r.step_path.replace(/\.[^/.]+$/, "")}_${i}`;
    const count = candidate.count_per_part[partId] || 0;
    const qtyLabel = r.quantity <= 0 ? "自動(最大)" : r.quantity;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.step_path}</td><td>${qtyLabel}</td><td>${count}</td>` +
      `<td>${r.part_area.toFixed(2)}</td><td>${r.flattened_area.toFixed(2)}</td>`;
    tbody.appendChild(tr);
  });
}

async function onDownloadZip() {
  window.location.href = `api/jobs/${currentJobId}/download/zip`;
}

async function onLogout() {
  await apiFetch("auth/logout", {method: "POST"});
  window.location.href = "login";
}

init();
