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
let selectedFileQuantities = [];
let manualShapes = [];
let nextManualShapeId = 1;
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
    document.getElementById("density").value = config.density;
  }

  document.getElementById("file-input").addEventListener("change", onFilesSelected);
  document.getElementById("add-rectangle-btn").addEventListener("click", () => addManualShape("rectangle"));
  document.getElementById("add-circle-btn").addEventListener("click", () => addManualShape("circle"));
  document.getElementById("clear-all-btn").addEventListener("click", onClearAllParts);
  document.getElementById("export-params-btn").addEventListener("click", onExportParams);
  document.getElementById("import-params-btn").addEventListener("click", () => {
    if (!document.getElementById("run-btn").disabled) document.getElementById("param-import-input").click();
  });
  document.getElementById("param-import-input").addEventListener("change", onParamFileSelected);
  document.getElementById("run-btn").addEventListener("click", onRun);
  document.getElementById("logout-btn").addEventListener("click", onLogout);
  document.getElementById("download-zip-btn").addEventListener("click", onDownloadZip);
  document.getElementById("download-summary-btn").addEventListener("click", onDownloadSummary);
}

function onFilesSelected(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;
  if (selectedFiles.some((file) => file.pending)) {
    const unmatched = [];
    files.forEach((file) => {
      const index = selectedFiles.findIndex((item) => item.pending && item.name === file.name);
      if (index === -1) unmatched.push(file.name);
      else selectedFiles[index] = file;
    });
    document.getElementById("error-text").textContent = unmatched.length
      ? `Excel の再選択待ち部品と一致しないファイル: ${unmatched.join("、")}` : "";
    e.target.value = "";
  } else {
    selectedFiles = files;
    selectedFileQuantities = selectedFiles.map(() => 1);
  }
  renderPartsTable();
}

const parameterKeys = ["sheet_w", "sheet_h", "thickness", "clearance", "density"];

function readParameterValues() {
  return Object.fromEntries(parameterKeys.map((key) => [key, Number(document.getElementById(key).value)]));
}

async function parameterError(response) {
  const data = await response.json().catch(() => ({}));
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((error) => `${error.loc.join(".")}: ${error.msg}`).join("\n");
  return "パラメータの保存・読み込みに失敗しました";
}

function setParameterBusy(busy) {
  document.querySelectorAll("#settings-panel input, #settings-panel button, #settings-panel select").forEach((element) => {
    element.disabled = busy;
  });
  if (!busy) renderPartsTable();
}

async function onExportParams() {
  if (document.getElementById("run-btn").disabled) return;
  const errorText = document.getElementById("error-text");
  errorText.textContent = "";
  try {
    const payload = {
      ...readParameterValues(),
      step_parts: selectedFiles.map((file, index) => ({filename: file.name, quantity: Number(selectedFileQuantities[index])})),
      manual_parts: manualShapes.map((shape) => shape.shape_type === "rectangle" ? {
        shape_type: shape.shape_type, width: Number(shape.width), height: Number(shape.height), quantity: Number(shape.quantity),
      } : {
        shape_type: shape.shape_type, circle_unit: shape.circle_unit, circle_value: Number(shape.circle_value), quantity: Number(shape.quantity),
      }),
    };
    setParameterBusy(true);
    const response = await apiFetch("api/config/export", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parameterError(response));
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "netsingtool_params.xlsx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    errorText.textContent = error.message;
  } finally {
    setParameterBusy(false);
  }
}

async function onParamFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  if (document.getElementById("run-btn").disabled) { e.target.value = ""; return; }
  if (!window.confirm("現在の部品リスト・定尺パラメータを、Excel の内容で置き換えますか？")) {
    e.target.value = "";
    return;
  }
  const errorText = document.getElementById("error-text");
  errorText.textContent = "";
  let stepNames = [];
  try {
    setParameterBusy(true);
    const body = new FormData();
    body.append("file", file);
    const response = await apiFetch("api/config/import", {method: "POST", body});
    if (!response.ok) throw new Error(await parameterError(response));
    const data = await response.json();
    parameterKeys.forEach((key) => { document.getElementById(key).value = data[key]; });
    selectedFiles = data.step_parts.map((part) => ({name: part.filename, pending: true}));
    selectedFileQuantities = data.step_parts.map((part) => part.quantity);
    document.getElementById("file-input").value = "";
    manualShapes = data.manual_parts.map((part) => ({
      id: nextManualShapeId++, shape_type: part.shape_type,
      width: String(part.width ?? 0), height: String(part.height ?? 0),
      circle_unit: part.circle_unit, circle_value: String(part.circle_value ?? 0), quantity: String(part.quantity),
    }));
    stepNames = data.step_parts.map((part) => part.filename);
    document.getElementById("status-text").textContent = "パラメータを読み込みました";
  } catch (error) {
    errorText.textContent = error.message;
  } finally {
    e.target.value = "";
    setParameterBusy(false);
  }
  if (stepNames.length) {
    window.alert(`次の STEP ファイルを再アップロードするため、元のファイルを再選択してください。\n\n${stepNames.join("\n")}\n\n選択ダイアログが表示されない場合は、STEP ファイル欄から選択してください。`);
    document.getElementById("file-input").click();
  }
}

function createNumberInput(value, onInput, options = {}) {
  const input = document.createElement("input");
  input.type = "number";
  input.value = value;
  input.step = options.step || "0.1";
  if (options.min !== undefined) input.min = options.min;
  if (options.max !== undefined) input.max = options.max;
  if (options.title) input.title = options.title;
  input.addEventListener("input", () => onInput(input.value));
  return input;
}

function addManualShape(shapeType) {
  manualShapes.push({
    id: nextManualShapeId++,
    shape_type: shapeType,
    width: "0",
    height: "0",
    circle_unit: "diameter",
    circle_value: "0",
    quantity: "1",
  });
  renderPartsTable();
}

function onClearAllParts() {
  if (selectedFiles.length === 0 && manualShapes.length === 0) return;
  if (!window.confirm("すべての部品を削除しますか？")) return;

  selectedFiles = [];
  selectedFileQuantities = [];
  manualShapes = [];
  document.getElementById("file-input").value = "";
  renderPartsTable();
}

function renderPartsTable() {
  const tbody = document.querySelector("#parts-table tbody");
  tbody.innerHTML = "";
  document.getElementById("clear-all-btn").disabled = selectedFiles.length === 0 && manualShapes.length === 0;
  selectedFiles.forEach((file, i) => {
    const tr = document.createElement("tr");
    const typeTd = document.createElement("td");
    typeTd.textContent = "STEP";
    const nameTd = document.createElement("td");
    nameTd.textContent = file.pending ? `${file.name}（再選択待ち）` : file.name;
    const qtyTd = document.createElement("td");
    const qtyInput = createNumberInput(
      selectedFileQuantities[i],
      (value) => { selectedFileQuantities[i] = value; },
      {step: "1", max: "10000", title: "負数で自動計算(最大取り数)"},
    );
    qtyTd.appendChild(qtyInput);
    const actionTd = document.createElement("td");
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "icon-button danger";
    removeButton.title = "このファイルを削除";
    removeButton.setAttribute("aria-label", `${file.name}を削除`);
    removeButton.textContent = "×";
    removeButton.addEventListener("click", () => {
      selectedFiles.splice(i, 1);
      selectedFileQuantities.splice(i, 1);
      document.getElementById("file-input").value = "";
      renderPartsTable();
    });
    actionTd.appendChild(removeButton);
    tr.appendChild(typeTd);
    tr.appendChild(nameTd);
    tr.appendChild(qtyTd);
    tr.appendChild(actionTd);
    tbody.appendChild(tr);
  });

  manualShapes.forEach((shape, shapeIndex) => {
    const tr = document.createElement("tr");
    const typeTd = document.createElement("td");
    typeTd.textContent = shape.shape_type === "rectangle" ? "矩形" : "円形";

    const dimensionsTd = document.createElement("td");
    const fields = document.createElement("div");
    fields.className = "shape-fields";
    if (shape.shape_type === "rectangle") {
      fields.append("幅(mm)", createNumberInput(
        shape.width, (value) => { shape.width = value; }, {min: "0.1", max: "100000"},
      ));
      fields.append("高さ(mm)", createNumberInput(
        shape.height, (value) => { shape.height = value; }, {min: "0.1", max: "100000"},
      ));
    } else {
      const unit = document.createElement("select");
      unit.innerHTML = '<option value="diameter">直径</option><option value="radius">半径</option>';
      unit.value = shape.circle_unit;
      unit.addEventListener("change", () => { shape.circle_unit = unit.value; });
      fields.append(unit, createNumberInput(
        shape.circle_value,
        (value) => { shape.circle_value = value; },
        {min: "0.1", max: "100000"},
      ), "mm");
    }
    dimensionsTd.appendChild(fields);

    const qtyTd = document.createElement("td");
    qtyTd.appendChild(createNumberInput(
      shape.quantity,
      (value) => { shape.quantity = value; },
      {step: "1", max: "10000", title: "0または負数で自動計算(最大取り数)"},
    ));

    const actionTd = document.createElement("td");
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "icon-button danger";
    removeButton.title = "この形状を削除";
    removeButton.setAttribute("aria-label", `手動形状${shapeIndex + 1}を削除`);
    removeButton.textContent = "×";
    removeButton.addEventListener("click", () => {
      manualShapes = manualShapes.filter((item) => item.id !== shape.id);
      renderPartsTable();
    });
    actionTd.appendChild(removeButton);

    tr.append(typeTd, dimensionsTd, qtyTd, actionTd);
    tbody.appendChild(tr);
  });
}

function buildManualParts() {
  return manualShapes.map((shape, index) => {
    const quantity = parseInt(shape.quantity, 10);
    if (shape.shape_type === "rectangle") {
      const width = parseFloat(shape.width);
      const height = parseFloat(shape.height);
      if (!(width > 0) || !(height > 0)) {
        throw new Error(`矩形${index + 1}の幅と高さを入力してください`);
      }
      return {shape_type: "rectangle", width, height, quantity: Number.isNaN(quantity) ? 1 : quantity};
    }

    const value = parseFloat(shape.circle_value);
    if (!(value > 0)) {
      throw new Error(`円形${index + 1}の直径または半径を入力してください`);
    }
    const radius = shape.circle_unit === "diameter" ? value / 2 : value;
    return {shape_type: "circle", radius, quantity: Number.isNaN(quantity) ? 1 : quantity};
  });
}

async function onRun() {
  const errorText = document.getElementById("error-text");
  const statusText = document.getElementById("status-text");
  errorText.textContent = "";
  if (selectedFiles.some((file) => file.pending)) {
    errorText.textContent = "再選択待ちの STEP ファイルをすべて選択してから実行してください";
    document.getElementById("file-input").click();
    return;
  }
  if (selectedFiles.length === 0 && manualShapes.length === 0) {
    errorText.textContent = "STEP ファイルまたは手動形状を追加してください";
    return;
  }

  const sheet_w = parseFloat(document.getElementById("sheet_w").value);
  const sheet_h = parseFloat(document.getElementById("sheet_h").value);
  const thickness = parseFloat(document.getElementById("thickness").value);
  const clearance = parseFloat(document.getElementById("clearance").value);
  const density = parseFloat(document.getElementById("density").value);

  try {
    const manual_parts = buildManualParts();
    document.getElementById("run-btn").disabled = true;
    statusText.textContent = selectedFiles.length > 0 ? "アップロード中…" : "ジョブ作成中…";

    let uploads = [];
    if (selectedFiles.length > 0) {
      const formData = new FormData();
      selectedFiles.forEach((file) => formData.append("files", file));
      const uploadRes = await apiFetch("api/uploads", {method: "POST", body: formData});
      if (!uploadRes.ok) {
        const data = await uploadRes.json().catch(() => ({}));
        throw new Error(data.detail || "アップロードに失敗しました");
      }
      uploads = (await uploadRes.json()).uploads;
    }

    const parts = uploads.map((upload, i) => {
      const parsed = parseInt(selectedFileQuantities[i], 10);
      return {upload_id: upload.upload_id, quantity: Number.isNaN(parsed) ? 1 : parsed};
    });

    const jobRes = await apiFetch("api/jobs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        parts,
        manual_parts,
        sheet_w,
        sheet_h,
        thickness,
        clearance,
        density,
      }),
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
      body: JSON.stringify({
        parts: [],
        sheet_w,
        sheet_h,
        thickness,
        clearance,
        density,
      }),
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

  const thickness = parseFloat(document.getElementById("thickness").value) || 0;
  const density = parseFloat(document.getElementById("density").value) || 0;

  const tbody = document.querySelector("#breakdown-table tbody");
  tbody.innerHTML = "";
  currentResults.forEach((r, i) => {
    const partId = r.part_id || `${r.step_path.replace(/\.[^/.]+$/, "")}_${i}`;
    const count = candidate.count_per_part[partId] || 0;
    const qtyLabel = r.quantity <= 0 ? "自動(最大)" : r.quantity;
    const partArea = r.flattened_area;
    const partVolume = partArea * thickness;
    const partWeightKg = partArea * count * thickness * density / 1e6;
    const weightFormula = `(= ${partArea.toFixed(2)}mm² × ${count}個 × ${thickness}mm × ${density}g/cm³ ÷ 1,000,000)`;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.display_name || r.step_path}</td><td>${qtyLabel}</td><td>${count}</td>` +
      `<td>${r.width.toFixed(2)}</td><td>${r.height.toFixed(2)}</td>` +
      `<td>${partArea.toFixed(2)}</td><td>${partVolume.toFixed(2)}</td>` +
      `<td>${partWeightKg.toFixed(3)}kg (${Math.round(partWeightKg * 1000)}g)<small class="formula">${weightFormula}</small></td>`;
    tbody.appendChild(tr);
  });

  const scrapArea = Math.max(0, candidate.sheet_area - candidate.total_used_area - candidate.total_hole_area);
  const partsWeightKg = candidate.total_used_area * thickness * density / 1e6;
  const scrapWeightKg = scrapArea * thickness * density / 1e6;
  const partsFormula = `(= ${candidate.total_used_area.toFixed(2)}mm² × ${thickness}mm × ${density}g/cm³ ÷ 1,000,000)`;
  const scrapFormula = `(= ${scrapArea.toFixed(2)}mm² × ${thickness}mm × ${density}g/cm³ ÷ 1,000,000)`;
  document.getElementById("weight-summary").innerHTML =
    `部材重量合計: ${partsWeightKg.toFixed(3)}kg (${Math.round(partsWeightKg * 1000)}g) <small class="formula">${partsFormula}</small>　` +
    `端材重量: ${scrapWeightKg.toFixed(3)}kg (${Math.round(scrapWeightKg * 1000)}g) <small class="formula">${scrapFormula}</small>`;
}

async function onDownloadZip() {
  window.location.href = `api/jobs/${currentJobId}/download/zip`;
}

function onDownloadSummary() {
  window.location.href = `api/jobs/${currentJobId}/download/summary`;
}

async function onLogout() {
  await apiFetch("auth/logout", {method: "POST"});
  window.location.href = "login";
}

init();
