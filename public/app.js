const state = {
  capabilities: null,
  selectedFile: null,
};

const fileInput = document.querySelector("#fileInput");
const dropzone = document.querySelector("#dropzone");
const fileTitle = document.querySelector("#fileTitle");
const fileMeta = document.querySelector("#fileMeta");
const targetSelect = document.querySelector("#targetSelect");
const convertButton = document.querySelector("#convertButton");
const convertForm = document.querySelector("#convertForm");
const toolStatus = document.querySelector("#toolStatus");
const operationGrid = document.querySelector("#operationGrid");
const resultPanel = document.querySelector("#resultPanel");
const resultTitle = document.querySelector("#resultTitle");
const resultMeta = document.querySelector("#resultMeta");
const downloadLink = document.querySelector("#downloadLink");
const refreshButton = document.querySelector("#refreshButton");

function formatBytes(value) {
  if (!Number.isFinite(value)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)}${units[index]}`;
}

function formatExpiry(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.toLocaleString()}까지`;
}

function extensionOf(file) {
  const name = file?.name || "";
  const dot = name.lastIndexOf(".");
  return dot > -1 ? name.slice(dot + 1).toLowerCase() : "";
}

function targetsFor(ext) {
  if (!state.capabilities) return [];
  const targets = new Set();
  for (const op of state.capabilities.operations) {
    if (op.from.includes("*") || op.from.includes(ext)) {
      for (const target of op.to) {
        if (target !== ext) targets.add(target);
      }
    }
  }
  return [...targets].sort();
}

function toolLabel(name) {
  return {
    ffmpeg: "ffmpeg",
    libreoffice: "LibreOffice",
    imagemagick: "ImageMagick",
    "g++": "C++",
    java: "Java",
    rust: "Rust",
    csharp: "C#",
    cpp_probe: "C++ helper",
    rust_probe: "Rust helper",
    java_probe: "Java helper",
    csharp_probe: "C# helper",
  }[name] || name;
}

function renderTools() {
  toolStatus.replaceChildren();
  const tools = {
    ...(state.capabilities?.tools || {}),
    ...(state.capabilities?.helpers || {}),
  };
  for (const [name, path] of Object.entries(tools)) {
    const badge = document.createElement("span");
    badge.className = `badge ${path ? "ready" : "missing"}`;
    badge.textContent = `${toolLabel(name)} ${path ? "ready" : "missing"}`;
    toolStatus.appendChild(badge);
  }
}

function renderOperations() {
  operationGrid.replaceChildren();
  const operations = state.capabilities?.operations || [];
  for (const op of operations) {
    const item = document.createElement("article");
    item.className = `operation ${op.available ? "" : "unavailable"}`;

    const title = document.createElement("h3");
    title.textContent = op.label;

    const formats = document.createElement("p");
    formats.textContent = `${op.from.slice(0, 9).join(", ")} -> ${op.to.join(", ")}`;

    const engine = document.createElement("p");
    engine.textContent = op.engine;

    const status = document.createElement("span");
    status.className = `operation-state ${op.available ? "ready" : "missing"}`;
    status.textContent = op.available ? "사용 가능" : "엔진 없음";

    item.append(title, formats, engine, status);
    operationGrid.appendChild(item);
  }
}

function setFile(file) {
  state.selectedFile = file;
  resultPanel.hidden = true;

  if (!file) {
    fileTitle.textContent = "파일 선택";
    fileMeta.textContent = `최대 ${formatBytes(state.capabilities?.maxUploadBytes || 0)}`;
    targetSelect.innerHTML = '<option value="">파일을 먼저 선택하세요</option>';
    targetSelect.disabled = true;
    convertButton.disabled = true;
    return;
  }

  const ext = extensionOf(file);
  const targets = targetsFor(ext);
  fileTitle.textContent = file.name;
  fileMeta.textContent = `${formatBytes(file.size)} · .${ext || "unknown"}`;

  const maxBytes = state.capabilities?.maxUploadBytes || 0;
  if (maxBytes && file.size > maxBytes) {
    targetSelect.innerHTML = '<option value="">용량 제한 초과</option>';
    targetSelect.disabled = true;
    convertButton.disabled = true;
    fileMeta.textContent = `${formatBytes(file.size)} · 최대 ${formatBytes(maxBytes)}`;
    return;
  }

  targetSelect.replaceChildren();
  if (targets.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "지원 형식 없음";
    targetSelect.appendChild(option);
    targetSelect.disabled = true;
    convertButton.disabled = true;
    return;
  }

  for (const target of targets) {
    const option = document.createElement("option");
    option.value = target;
    option.textContent = target.toUpperCase();
    targetSelect.appendChild(option);
  }
  targetSelect.disabled = false;
  convertButton.disabled = false;
}

async function loadCapabilities() {
  const response = await fetch("/api/capabilities");
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "capabilities failed");
  state.capabilities = data;
  renderTools();
  renderOperations();
  setFile(state.selectedFile);
}

async function convertSelectedFile(event) {
  event.preventDefault();
  const file = state.selectedFile;
  if (!file || !targetSelect.value) return;
  const maxBytes = state.capabilities?.maxUploadBytes || 0;
  if (maxBytes && file.size > maxBytes) {
    resultTitle.textContent = "변환 실패";
    resultMeta.textContent = `최대 ${formatBytes(maxBytes)}까지 업로드할 수 있습니다.`;
    downloadLink.hidden = true;
    resultPanel.hidden = false;
    return;
  }

  convertButton.disabled = true;
  convertButton.textContent = "변환 중";
  resultPanel.hidden = true;
  downloadLink.hidden = true;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("target", targetSelect.value);

  try {
    const response = await fetch("/convert", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "변환 실패");
    }

    resultTitle.textContent = data.outputName;
    resultMeta.textContent = [formatBytes(data.size), formatExpiry(data.expiresAt)].filter(Boolean).join(" · ");
    downloadLink.href = data.downloadUrl;
    downloadLink.download = data.outputName;
    downloadLink.hidden = false;
    resultPanel.hidden = false;
  } catch (error) {
    resultTitle.textContent = "변환 실패";
    resultMeta.textContent = error.message;
    downloadLink.href = "#";
    downloadLink.hidden = true;
    resultPanel.hidden = false;
  } finally {
    convertButton.textContent = "변환";
    convertButton.disabled = !state.selectedFile || !targetSelect.value;
  }
}

fileInput.addEventListener("change", () => {
  setFile(fileInput.files[0] || null);
});

for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  });
}

dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  setFile(file);
});

convertForm.addEventListener("submit", convertSelectedFile);
refreshButton.addEventListener("click", loadCapabilities);

loadCapabilities().catch((error) => {
  resultTitle.textContent = "초기화 실패";
  resultMeta.textContent = error.message;
  downloadLink.hidden = true;
  resultPanel.hidden = false;
});
