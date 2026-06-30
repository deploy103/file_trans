const apiBaseFromQuery = new URLSearchParams(location.search).get("api");
const defaultSplitApiBase = location.port && !["8000", "8766"].includes(location.port)
  ? "http://127.0.0.1:8766"
  : "";
const API_BASE = String(
  window.FILE_TRANS_API_BASE || apiBaseFromQuery || defaultSplitApiBase
).replace(/\/$/, "");

const MAX_SELECTED_FILES = 30;
const MAX_BROWSER_ZIP_BYTES = 512 * 1024 * 1024;

const SOURCE_ALIASES = {
  htm: ["htm", "html"],
  html: ["htm", "html"],
  jpeg: ["jpg", "jpeg"],
  jpg: ["jpg", "jpeg"],
  mpeg: ["mpeg", "mpg"],
  mpg: ["mpeg", "mpg"],
  tif: ["tif", "tiff"],
  tiff: ["tif", "tiff"],
  yaml: ["yaml", "yml"],
  yml: ["yaml", "yml"],
  video: ["3g2", "3gp", "avi", "flv", "m2ts", "m4v", "mkv", "mov", "mp4", "mpeg", "mpg", "mts", "ogv", "ts", "webm", "wmv"],
  audio: ["aac", "aif", "aiff", "amr", "caf", "flac", "m4a", "mid", "midi", "mp3", "ogg", "opus", "wav", "wma"],
  image: ["avif", "bmp", "gif", "heic", "ico", "jpeg", "jpg", "pbm", "pgm", "png", "pnm", "ppm", "psd", "tga", "tif", "tiff", "webp"],
  file: null,
};

const TOOL_GROUPS = [
  {
    title: "문서 & PDF",
    icon: "icon-doc",
    tools: [
      { from: "hwp", to: "pdf", label: "HWP → PDF" },
      { from: "hwpx", to: "pdf", label: "HWPX → PDF" },
      { from: "docx", to: "pdf", label: "DOCX → PDF" },
      { from: "pptx", to: "pdf", label: "PPTX → PDF" },
      { from: "html", to: "pdf", label: "HTML → PDF" },
      { from: "txt", to: "pdf", label: "TXT → PDF" },
      { from: "md", to: "pdf", label: "MD → PDF" },
      "separator",
      { from: "pdf", to: "jpg", label: "PDF → JPG" },
      { from: "pdf", to: "png", label: "PDF → PNG" },
      { from: "pdf", to: "txt", label: "PDF → TXT" },
    ],
  },
  {
    title: "이미지",
    icon: "icon-image",
    tools: [
      { from: "webp", to: "png", label: "WEBP → PNG" },
      { from: "webp", to: "jpg", label: "WEBP → JPG" },
      { from: "heic", to: "jpg", label: "HEIC → JPG" },
      { from: "avif", to: "jpg", label: "AVIF → JPG" },
      { from: "jpg", to: "png", label: "JPG → PNG" },
      { from: "png", to: "jpg", label: "PNG → JPG" },
      { from: "bmp", to: "jpg", label: "BMP → JPG" },
      { from: "tiff", to: "jpg", label: "TIFF → JPG" },
      "separator",
      { from: "image", to: "pdf", label: "이미지 → PDF" },
    ],
  },
  {
    title: "동영상 & 오디오",
    icon: "icon-media",
    tools: [
      { from: "mp4", to: "mp3", label: "MP4 → MP3" },
      { from: "video", to: "mp3", label: "영상 → MP3" },
      { from: "video", to: "gif", label: "영상 → GIF" },
      { from: "mov", to: "mp4", label: "MOV → MP4" },
      { from: "mkv", to: "mp4", label: "MKV → MP4" },
      { from: "webm", to: "mp4", label: "WEBM → MP4" },
      "separator",
      { from: "mp3", to: "wav", label: "MP3 → WAV" },
      { from: "wav", to: "mp3", label: "WAV → MP3" },
      { from: "flac", to: "mp3", label: "FLAC → MP3" },
      { from: "mp3", to: "ogg", label: "MP3 → OGG" },
    ],
  },
  {
    title: "데이터 & 기타",
    icon: "icon-data",
    tools: [
      { from: "csv", to: "json", label: "CSV → JSON" },
      { from: "tsv", to: "json", label: "TSV → JSON" },
      { from: "json", to: "csv", label: "JSON → CSV" },
      { from: "ndjson", to: "json", label: "NDJSON → JSON" },
      "separator",
      { from: "srt", to: "vtt", label: "SRT → VTT" },
      { from: "vtt", to: "srt", label: "VTT → SRT" },
      "separator",
      { from: "txt", to: "html", label: "TXT → HTML" },
      { from: "md", to: "html", label: "MD → HTML" },
      { from: "file", to: "zip", label: "모든 파일 → ZIP" },
    ],
  },
];

const state = {
  capabilities: null,
  files: [],
  preset: null,
  converting: false,
};

const toolPage = document.querySelector("#toolPage");
const converterPage = document.querySelector("#converterPage");
const toolGrid = document.querySelector("#toolGrid");
const toolSubtitle = document.querySelector("#toolSubtitle");
const uploadSection = document.querySelector("#uploadSection");
const controlSection = document.querySelector("#convertForm");
const dropzone = document.querySelector("#dropzone");
const subDropzone = document.querySelector("#subDropzone");
const fileInput = document.querySelector("#fileInput");
const fileList = document.querySelector("#fileList");
const fileCountBadge = document.querySelector("#fileCountBadge");
const workspaceStatusText = document.querySelector("#workspaceStatusText");
const actionReady = document.querySelector("#actionReady");
const actionDone = document.querySelector("#actionDone");
const addMoreButton = document.querySelector("#addMoreButton");
const convertButton = document.querySelector("#convertButton");
const resetButton = document.querySelector("#resetButton");
const downloadAllButton = document.querySelector("#downloadAllButton");
const downloadZipButton = document.querySelector("#downloadZipButton");
const toolStatus = document.querySelector("#toolStatus");
const routeBadge = document.querySelector("#routeBadge");
const routeSubtitle = document.querySelector("#routeSubtitle");
const dropTitle = document.querySelector("#dropTitle");
const dropMeta = document.querySelector("#dropMeta");
const navHome = document.querySelector("[data-nav-home]");
const navTools = document.querySelector("[data-nav-tools]");

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function routePath(tool) {
  return `/${tool.from}to${tool.to}/tran`;
}

function labelForToken(token) {
  if (token === "file") return "파일";
  if (token === "image") return "이미지";
  if (token === "video") return "영상";
  if (token === "audio") return "오디오";
  return token.toUpperCase();
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatExpiry(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })}까지`;
}

function extensionOf(file) {
  const name = file?.name || "";
  const dot = name.lastIndexOf(".");
  return dot > -1 ? name.slice(dot + 1).toLowerCase() : "";
}

function sourceExts(source) {
  if (Object.prototype.hasOwnProperty.call(SOURCE_ALIASES, source)) {
    return SOURCE_ALIASES[source] || state.capabilities?.inputFormats || [];
  }
  return [source];
}

function targetsForExt(ext) {
  if (!state.capabilities || !ext) return [];
  const targets = new Set();
  for (const op of state.capabilities.operations) {
    if (!op.available) continue;
    if (op.from.includes("*") || op.from.includes(ext)) {
      for (const target of op.to) {
        if (target !== ext) targets.add(target);
      }
    }
  }
  return [...targets].sort();
}

function toolAvailable(tool) {
  return sourceExts(tool.from).some((ext) => targetsForExt(ext).includes(tool.to));
}

function routePresetFromPath(pathname) {
  const match = pathname.match(/^\/([a-z0-9]+)to([a-z0-9]+)\/tran\/?$/i);
  if (!match) return null;
  const [, from, to] = match.map((item) => item.toLowerCase());
  const configured = TOOL_GROUPS.flatMap((group) => group.tools)
    .filter((tool) => tool !== "separator")
    .find((tool) => tool.from === from && tool.to === to);
  if (configured) return configured;
  if (state.capabilities?.inputFormats?.includes(from) && targetsForExt(from).includes(to)) {
    return { from, to, label: `${labelForToken(from)} → ${labelForToken(to)}` };
  }
  return { from, to, label: `${labelForToken(from)} → ${labelForToken(to)}`, unavailable: true };
}

function toolLabel(name) {
  return {
    ffmpeg: "ffmpeg",
    libreoffice: "LibreOffice",
    hwpfilter: "HWP 필터",
    imagemagick: "ImageMagick",
    poppler: "Poppler",
    pandoc: "Pandoc",
    calibre: "Calibre",
  }[name] || name;
}

function renderTools() {
  toolStatus.replaceChildren();
  const tools = state.capabilities?.tools || {};
  for (const [name, ready] of Object.entries(tools)) {
    const badge = document.createElement("span");
    badge.className = `badge ${ready ? "ready" : "missing"}`;
    badge.textContent = `${toolLabel(name)} ${ready ? "사용 가능" : "없음"}`;
    toolStatus.appendChild(badge);
  }
}

function renderToolGrid() {
  const inputCount = state.capabilities?.inputFormatCount || 0;
  const targetCount = state.capabilities?.targetFormatCount || 0;
  if (inputCount && targetCount) {
    toolSubtitle.textContent = `현재 입력 형식 ${inputCount}개, 출력 형식 ${targetCount}개를 지원합니다. 원하는 작업을 선택하면 바로 변환 화면으로 이동합니다.`;
  }

  toolGrid.replaceChildren();
  for (const group of TOOL_GROUPS) {
    const card = document.createElement("article");
    card.className = "tool-card";

    const heading = document.createElement("div");
    heading.className = "tool-card-title";
    const icon = document.createElement("span");
    icon.className = `card-icon ${group.icon}`;
    icon.setAttribute("aria-hidden", "true");
    const title = document.createElement("h2");
    title.textContent = group.title;
    heading.append(icon, title);

    const list = document.createElement("ul");
    list.className = "tool-list";

    for (const tool of group.tools) {
      const item = document.createElement("li");
      if (tool === "separator") {
        item.className = "tool-separator";
        list.appendChild(item);
        continue;
      }
      const link = document.createElement("a");
      const available = toolAvailable(tool);
      link.className = `tool-link ${available ? "" : "unavailable"}`;
      link.href = available ? routePath(tool) : "#";
      link.textContent = tool.label;
      if (!available) {
        link.title = "현재 설치된 변환 엔진으로는 사용할 수 없습니다.";
        link.addEventListener("click", (event) => event.preventDefault());
      }
      item.appendChild(link);
      list.appendChild(item);
    }

    card.append(heading, list);
    toolGrid.appendChild(card);
  }
}

function showMain() {
  state.preset = null;
  state.files = [];
  state.converting = false;
  toolPage.hidden = false;
  converterPage.hidden = true;
  navHome.classList.remove("active");
  navTools.classList.add("active");
  document.title = "File Trans";
}

function showConverter(preset) {
  state.preset = preset;
  state.files = [];
  state.converting = false;
  toolPage.hidden = true;
  converterPage.hidden = false;
  navHome.classList.remove("active");
  navTools.classList.add("active");

  const sourceLabel = labelForToken(preset.from);
  const targetLabel = labelForToken(preset.to);
  routeBadge.textContent = `${sourceLabel} → ${targetLabel}`;
  routeSubtitle.textContent = `${sourceLabel} 파일을 로컬 백엔드에서 ${targetLabel} 형식으로 변환합니다.`;
  dropTitle.textContent = `${sourceLabel} 파일을 이곳으로 드래그하거나 클릭하여 추가하세요`;
  document.title = `${sourceLabel} to ${targetLabel} - File Trans`;

  const extList = sourceExts(preset.from);
  fileInput.accept = preset.from === "file" ? "" : extList.map((ext) => `.${ext}`).join(",");

  const maxBytes = state.capabilities?.maxUploadBytes || 0;
  dropMeta.textContent = preset.from === "file"
    ? `지원 형식 ${state.capabilities?.inputFormatCount || 0}개 이상 · 파일당 최대 ${formatBytes(maxBytes)} · 최대 ${MAX_SELECTED_FILES}개`
    : `허용 입력: ${extList.slice(0, 8).map((ext) => `.${ext}`).join(", ")}${extList.length > 8 ? "..." : ""} · 파일당 최대 ${formatBytes(maxBytes)} · 최대 ${MAX_SELECTED_FILES}개`;

  renderWorkspace();
  if (preset.unavailable || !toolAvailable(preset)) {
    addInvalidFileMessage("현재 설치된 변환 엔진으로는 이 변환을 사용할 수 없습니다.");
  }
}

function renderRoute() {
  const preset = routePresetFromPath(location.pathname);
  if (!preset) {
    showMain();
    return;
  }
  showConverter(preset);
}

function fileMatchesPreset(file, preset) {
  if (!file || !preset) return false;
  const ext = extensionOf(file);
  return sourceExts(preset.from).includes(ext) && targetsForExt(ext).includes(preset.to);
}

function fileRowId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `file_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function invalidFileRow(message) {
  return {
    id: fileRowId(),
    file: null,
    status: "error",
    progress: 0,
    error: message,
  };
}

function addInvalidFileMessage(message) {
  state.files.push(invalidFileRow(message));
  renderWorkspace();
}

function addFiles(files) {
  if (state.converting) return;
  const incoming = Array.from(files || []);
  if (!incoming.length) return;

  const selectedCount = state.files.filter((item) => item.file).length;
  const availableSlots = Math.max(0, MAX_SELECTED_FILES - selectedCount);
  const acceptedFiles = incoming.slice(0, availableSlots);

  for (const file of acceptedFiles) {
    const maxBytes = state.capabilities?.maxUploadBytes || 0;
    const row = {
      id: fileRowId(),
      file,
      status: "ready",
      progress: 0,
      result: null,
      error: "",
    };
    if (maxBytes && file.size > maxBytes) {
      row.status = "error";
      row.error = `최대 ${formatBytes(maxBytes)}까지 업로드할 수 있습니다.`;
    } else if (!fileMatchesPreset(file, state.preset)) {
      row.status = "error";
      row.error = `${routeBadge.textContent} 도구에서 지원하지 않는 입력 파일입니다.`;
    }
    state.files.push(row);
  }
  if (acceptedFiles.length < incoming.length) {
    state.files.push(invalidFileRow(`한 작업에는 최대 ${MAX_SELECTED_FILES}개까지 추가할 수 있습니다.`));
  }
  fileInput.value = "";
  renderWorkspace();
}

function removeFile(id) {
  if (state.converting) return;
  state.files = state.files.filter((item) => item.id !== id);
  renderWorkspace();
}

function readyFiles() {
  return state.files.filter((item) => item.status === "ready");
}

function doneFiles() {
  return state.files.filter((item) => item.status === "done" && item.result?.downloadUrl);
}

function renderWorkspace() {
  const hasFiles = state.files.length > 0;
  const selectedFileCount = state.files.filter((item) => item.file).length;
  uploadSection.hidden = hasFiles;
  controlSection.hidden = !hasFiles;
  fileCountBadge.textContent = String(selectedFileCount);
  fileList.replaceChildren();

  if (!hasFiles) {
    workspaceStatusText.textContent = "변환할 파일을 추가하고 시작 버튼을 눌러주세요.";
    return;
  }

  const allDone = state.files.length > 0 && state.files.every((item) => item.status === "done" || item.status === "error");
  const anyConverting = state.files.some((item) => item.status === "converting");
  const readyCount = readyFiles().length;
  const errorCount = state.files.filter((item) => item.status === "error").length;

  if (anyConverting || state.converting) {
    workspaceStatusText.textContent = "파일을 변환하는 중입니다...";
  } else if (allDone && doneFiles().length) {
    workspaceStatusText.textContent = errorCount ? "변환이 끝났고 일부 파일은 실패했습니다." : "모든 파일 변환이 완료되었습니다.";
  } else if (readyCount) {
    workspaceStatusText.textContent = "변환할 파일을 추가하고 시작 버튼을 눌러주세요.";
  } else {
    workspaceStatusText.textContent = "변환 가능한 파일이 없습니다.";
  }

  actionReady.hidden = allDone && !state.converting && doneFiles().length > 0;
  actionDone.hidden = !actionReady.hidden;
  subDropzone.hidden = state.converting || actionDone.hidden === false;
  convertButton.disabled = state.converting || readyCount === 0;

  for (const item of state.files) {
    fileList.appendChild(renderFileRow(item));
  }
}

function renderFileRow(item) {
  const row = document.createElement("article");
  row.className = `file-row ${item.status}`;
  row.dataset.id = item.id;

  const ext = document.createElement("span");
  ext.className = "file-ext";
  ext.textContent = item.file ? extensionOf(item.file) || "file" : "!";

  const copy = document.createElement("div");
  copy.className = "file-copy";

  const name = document.createElement("span");
  name.className = "file-name";
  name.title = item.file?.name || item.error || "오류";
  name.textContent = item.file?.name || "사용할 수 없는 변환";

  const meta = document.createElement("span");
  meta.className = "file-size";
  if (item.status === "error") {
    meta.textContent = item.error || "변환 실패";
  } else if (item.status === "done") {
    meta.textContent = [item.result?.outputName, formatBytes(item.result?.size || 0), formatExpiry(item.result?.expiresAt)]
      .filter(Boolean)
      .join(" · ");
  } else {
    meta.textContent = `${formatBytes(item.file?.size || 0)} · ${labelForToken(state.preset.to)}로 변환`;
  }
  copy.append(name, meta);

  const action = document.createElement("div");
  action.className = "file-action";
  action.appendChild(renderFileAction(item));

  row.append(ext, copy, action);
  return row;
}

function renderFileAction(item) {
  if (item.status === "ready" || item.status === "error") {
    const button = document.createElement("button");
    button.className = "remove-file";
    button.type = "button";
    button.setAttribute("aria-label", "선택 파일 제거");
    button.addEventListener("click", () => removeFile(item.id));
    return button;
  }

  if (item.status === "converting") {
    const wrap = document.createElement("div");
    wrap.className = "row-progress";
    const percent = document.createElement("span");
    percent.textContent = `${Math.round(item.progress)}%`;
    const track = document.createElement("span");
    track.className = "row-progress-track";
    const bar = document.createElement("span");
    bar.className = "row-progress-bar";
    bar.style.width = `${item.progress}%`;
    track.appendChild(bar);
    wrap.append(percent, track);
    return wrap;
  }

  const link = document.createElement("a");
  link.className = "row-download";
  link.href = apiUrl(item.result.downloadUrl);
  link.download = item.result.outputName || "";
  link.textContent = "다운로드";
  return link;
}

function updateRow(id) {
  const existing = fileList.querySelector(`[data-id="${CSS.escape(id)}"]`);
  const item = state.files.find((candidate) => candidate.id === id);
  if (!existing || !item) {
    renderWorkspace();
    return;
  }
  existing.replaceWith(renderFileRow(item));
  const readyCount = readyFiles().length;
  convertButton.disabled = state.converting || readyCount === 0;
}

function setRowProgress(item, value) {
  item.progress = Math.max(0, Math.min(100, value));
  updateRow(item.id);
}

async function convertOne(item) {
  item.status = "converting";
  item.progress = 5;
  updateRow(item.id);

  const timer = setInterval(() => {
    if (item.status === "converting") {
      item.progress = Math.min(92, item.progress + 9);
      updateRow(item.id);
    }
  }, 260);

  const formData = new FormData();
  formData.append("file", item.file);
  formData.append("target", state.preset.to);

  try {
    const response = await fetch(apiUrl("/convert"), {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "변환 실패");
    item.status = "done";
    item.progress = 100;
    item.result = data;
    item.error = "";
  } catch (error) {
    item.status = "error";
    item.error = error.message;
  } finally {
    clearInterval(timer);
    updateRow(item.id);
  }
}

async function convertSelectedFiles(event) {
  event.preventDefault();
  if (state.converting || !readyFiles().length) return;
  state.converting = true;
  renderWorkspace();
  for (const item of [...readyFiles()]) {
    await convertOne(item);
  }
  state.converting = false;
  renderWorkspace();
}

function resetConversionState() {
  state.files = [];
  state.converting = false;
  fileInput.value = "";
  renderWorkspace();
}

function downloadAll() {
  for (const item of doneFiles()) {
    const link = document.createElement("a");
    link.href = apiUrl(item.result.downloadUrl);
    link.download = item.result.outputName || "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }
}

function makeCrc32Table() {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }
  return table;
}

const CRC32_TABLE = makeCrc32Table();

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value = CRC32_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  }
  return (value ^ 0xffffffff) >>> 0;
}

function dosTimestamp(date = new Date()) {
  const year = Math.max(1980, date.getFullYear());
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}

function concatUint8(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const output = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function headerBytes(size) {
  return new Uint8Array(size);
}

function writeZipHeader(view, values) {
  for (const [offset, size, value] of values) {
    if (size === 2) view.setUint16(offset, value, true);
    if (size === 4) view.setUint32(offset, value, true);
  }
}

function createZip(entries) {
  const encoder = new TextEncoder();
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  const stamp = dosTimestamp();

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const data = entry.data;
    const checksum = crc32(data);

    const localHeader = headerBytes(30);
    writeZipHeader(new DataView(localHeader.buffer), [
      [0, 4, 0x04034b50],
      [4, 2, 20],
      [6, 2, 0x0800],
      [8, 2, 0],
      [10, 2, stamp.time],
      [12, 2, stamp.day],
      [14, 4, checksum],
      [18, 4, data.length],
      [22, 4, data.length],
      [26, 2, nameBytes.length],
      [28, 2, 0],
    ]);
    localParts.push(localHeader, nameBytes, data);

    const centralHeader = headerBytes(46);
    writeZipHeader(new DataView(centralHeader.buffer), [
      [0, 4, 0x02014b50],
      [4, 2, 20],
      [6, 2, 20],
      [8, 2, 0x0800],
      [10, 2, 0],
      [12, 2, stamp.time],
      [14, 2, stamp.day],
      [16, 4, checksum],
      [20, 4, data.length],
      [24, 4, data.length],
      [28, 2, nameBytes.length],
      [30, 2, 0],
      [32, 2, 0],
      [34, 2, 0],
      [36, 2, 0],
      [38, 4, 0],
      [42, 4, offset],
    ]);
    centralParts.push(centralHeader, nameBytes);
    offset += localHeader.length + nameBytes.length + data.length;
  }

  const centralDirectory = concatUint8(centralParts);
  const end = headerBytes(22);
  writeZipHeader(new DataView(end.buffer), [
    [0, 4, 0x06054b50],
    [4, 2, 0],
    [6, 2, 0],
    [8, 2, entries.length],
    [10, 2, entries.length],
    [12, 4, centralDirectory.length],
    [16, 4, offset],
    [20, 2, 0],
  ]);

  return new Blob([concatUint8(localParts), centralDirectory, end], { type: "application/zip" });
}

function uniqueZipName(name, usedNames) {
  const fallback = "download.bin";
  const original = name || fallback;
  if (!usedNames.has(original)) {
    usedNames.add(original);
    return original;
  }

  const dot = original.lastIndexOf(".");
  const base = dot > 0 ? original.slice(0, dot) : original;
  const ext = dot > 0 ? original.slice(dot) : "";
  let index = 2;
  let candidate = `${base}-${index}${ext}`;
  while (usedNames.has(candidate)) {
    index += 1;
    candidate = `${base}-${index}${ext}`;
  }
  usedNames.add(candidate);
  return candidate;
}

async function downloadZip() {
  const items = doneFiles();
  if (!items.length) return;
  downloadZipButton.disabled = true;
  downloadZipButton.textContent = "ZIP 생성 중";
  try {
    const totalBytes = items.reduce((sum, item) => sum + Number(item.result?.size || 0), 0);
    if (totalBytes > MAX_BROWSER_ZIP_BYTES) {
      throw new Error(`브라우저 ZIP 다운로드는 총 ${formatBytes(MAX_BROWSER_ZIP_BYTES)}까지 지원합니다. 개별 다운로드를 사용해주세요.`);
    }

    const entries = [];
    const usedNames = new Set();
    for (const item of items) {
      const response = await fetch(apiUrl(item.result.downloadUrl));
      if (!response.ok) throw new Error(`${item.result.outputName} 다운로드 실패`);
      entries.push({
        name: uniqueZipName(item.result.outputName, usedNames),
        data: new Uint8Array(await response.arrayBuffer()),
      });
    }
    const blobUrl = URL.createObjectURL(createZip(entries));
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = `${state.preset.from}to${state.preset.to}-results.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  } catch (error) {
    addInvalidFileMessage(error.message);
  } finally {
    downloadZipButton.disabled = false;
    downloadZipButton.textContent = "ZIP 다운로드";
  }
}

function setupDropzone(element) {
  for (const eventName of ["dragenter", "dragover"]) {
    element.addEventListener(eventName, (event) => {
      event.preventDefault();
      element.classList.add("dragover");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    element.addEventListener(eventName, (event) => {
      event.preventDefault();
      element.classList.remove("dragover");
    });
  }
  element.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
  element.addEventListener("click", (event) => {
    if (event.target === fileInput) return;
    if (!state.converting) fileInput.click();
  });
  element.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (!state.converting) fileInput.click();
  });
}

async function loadCapabilities() {
  const response = await fetch(apiUrl("/api/capabilities"));
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || "capabilities failed");
  state.capabilities = data;
  renderTools();
  renderToolGrid();
  renderRoute();
}

setupDropzone(dropzone);
setupDropzone(subDropzone);
addMoreButton.addEventListener("click", () => {
  if (!state.converting) fileInput.click();
});
fileInput.addEventListener("change", () => addFiles(fileInput.files));
controlSection.addEventListener("submit", convertSelectedFiles);
resetButton.addEventListener("click", resetConversionState);
downloadAllButton.addEventListener("click", downloadAll);
downloadZipButton.addEventListener("click", downloadZip);
window.addEventListener("popstate", renderRoute);

loadCapabilities().catch((error) => {
  toolGrid.replaceChildren();
  const message = document.createElement("p");
  message.className = "tool-link unavailable";
  message.textContent = `백엔드 연결 실패: ${error.message}`;
  toolGrid.appendChild(message);
  showMain();
});
