const state = {
  projects: [],
  folders: [],
  project: null,
  shots: [],
  outline: { sentences: [] },
  view: "home",
  uploading: false,
  importingChannel: false,
  editMode: false,
  selected: new Set(),
  selectionAnchorIndex: null,
  dragShotIndexes: [],
  activeIndex: null,
  clipEnd: null,
  clipVideo: null,
  clipImage: null,
  clipIndex: null,
  detailClipEnd: null,
  splitMode: false,
  splitIndex: null,
  screencapMode: false,
  screencapIndex: null,
  activeSentenceIndex: null,
  undoStack: [],
  undoCaptureKey: null,
  contextSaveTimer: null,
  coverCropEdit: null,
  coverCropDrag: null,
  dragProjectId: null,
  hiddenFolders: new Set(),
  fullVideoOpen: false,
  dirty: false,
  detailResolutionResolver: null,
  analyzedContext: null,
  analysisJob: null,
  analysisPollTimer: null,
  analysisClockTimer: null,
  analysisStartedAt: null,
  chatSending: false,
  toastTimer: null,
};

const DEFAULT_QWEN_VIDEO_MODEL = "qwen3.5-omni-plus";
const QWEN_VIDEO_MODELS = new Set([
  "qwen3.5-omni-plus",
  "qwen3.7-plus",
  "qwen3-vl-plus",
  "qwen3-vl-flash",
  "qwen-vl-max-latest",
  "qwen-vl-plus-latest",
  "qwen2.5-vl-72b-instruct",
  "qwen2.5-vl-32b-instruct",
]);

const els = {
  projectMeta: document.querySelector("#projectMeta"),
  homeButton: document.querySelector("#homeButton"),
  projectSelect: document.querySelector("#projectSelect"),
  editToggle: document.querySelector("#editToggle"),
  saveButton: document.querySelector("#saveButton"),
  homeView: document.querySelector("#homeView"),
  studyView: document.querySelector("#studyView"),
  uploadDrop: document.querySelector("#uploadDrop"),
  uploadInput: document.querySelector("#uploadInput"),
  channelUrlField: document.querySelector("#channelUrlField"),
  channelLimitField: document.querySelector("#channelLimitField"),
  importChannelButton: document.querySelector("#importChannelButton"),
  uploadStatus: document.querySelector("#uploadStatus"),
  libraryCount: document.querySelector("#libraryCount"),
  createFolderButton: document.querySelector("#createFolderButton"),
  filmGrid: document.querySelector("#filmGrid"),
  statusText: document.querySelector("#statusText"),
  studySourcePanel: document.querySelector("#studySourcePanel"),
  openFolderButton: document.querySelector("#openFolderButton"),
  sourceLink: document.querySelector("#sourceLink"),
  socialStats: document.querySelector("#socialStats"),
  fullVideoPanel: document.querySelector("#fullVideoPanel"),
  fullVideoToggle: document.querySelector("#fullVideoToggle"),
  fullVideoFrame: document.querySelector("#fullVideoFrame"),
  fullVideo: document.querySelector("#fullVideo"),
  editHelp: document.querySelector("#editHelp"),
  editPanel: document.querySelector("#editPanel"),
  selectionCount: document.querySelector("#selectionCount"),
  selectionRange: document.querySelector("#selectionRange"),
  combineSelected: document.querySelector("#combineSelected"),
  combineWithNext: document.querySelector("#combineWithNext"),
  linkSentence: document.querySelector("#linkSentence"),
  removeFromSentence: document.querySelector("#removeFromSentence"),
  useSelectedAnalysis: document.querySelector("#useSelectedAnalysis"),
  excludeSelected: document.querySelector("#excludeSelected"),
  includeSelected: document.querySelector("#includeSelected"),
  includeAllShots: document.querySelector("#includeAllShots"),
  clearSelection: document.querySelector("#clearSelection"),
  undoEdit: document.querySelector("#undoEdit"),
  shotGrid: document.querySelector("#shotGrid"),
  sentencePopover: document.querySelector("#sentencePopover"),
  sentencePopoverLabel: document.querySelector("#sentencePopoverLabel"),
  sentencePopoverShots: document.querySelector("#sentencePopoverShots"),
  closeSentencePopover: document.querySelector("#closeSentencePopover"),
  sentenceTitleField: document.querySelector("#sentenceTitleField"),
  sentenceBeatField: document.querySelector("#sentenceBeatField"),
  sentenceIdeaField: document.querySelector("#sentenceIdeaField"),
  selectSentenceShots: document.querySelector("#selectSentenceShots"),
  removeSentence: document.querySelector("#removeSentence"),
  filmContextField: document.querySelector("#filmContextField"),
  modelField: document.querySelector("#modelField"),
  generateDetails: document.querySelector("#generateDetails"),
  reprocessVideo: document.querySelector("#reprocessVideo"),
  askThisFilm: document.querySelector("#askThisFilm"),
  exportForAi: document.querySelector("#exportForAi"),
  analysisScopeStatus: document.querySelector("#analysisScopeStatus"),
  analysisStatus: document.querySelector("#analysisStatus"),
  analysisProgress: document.querySelector("#analysisProgress"),
  analysisPhase: document.querySelector("#analysisPhase"),
  analysisElapsed: document.querySelector("#analysisElapsed"),
  analysisProgressBar: document.querySelector("#analysisProgressBar"),
  analysisProgressDetail: document.querySelector("#analysisProgressDetail"),
  analysisUsage: document.querySelector("#analysisUsage"),
  analysisHistory: document.querySelector("#analysisHistory"),
  analysisHistoryCount: document.querySelector("#analysisHistoryCount"),
  analysisHistoryList: document.querySelector("#analysisHistoryList"),
  detailResolution: document.querySelector("#detailResolution"),
  detailResolutionTitle: document.querySelector("#detailResolutionTitle"),
  detailResolutionSummary: document.querySelector("#detailResolutionSummary"),
  detailResolutionOptions: document.querySelector("#detailResolutionOptions"),
  cancelDetailResolution: document.querySelector("#cancelDetailResolution"),
  detailView: document.querySelector("#detailView"),
  closeDetail: document.querySelector("#closeDetail"),
  prevShot: document.querySelector("#prevShot"),
  nextShot: document.querySelector("#nextShot"),
  detailImage: document.querySelector("#detailImage"),
  detailVideo: document.querySelector("#detailVideo"),
  detailPlayOverlay: document.querySelector("#detailPlayOverlay"),
  detailCounter: document.querySelector("#detailCounter"),
  detailTiming: document.querySelector("#detailTiming"),
  detailSentenceTitle: document.querySelector("#detailSentenceTitle"),
  playDetailShot: document.querySelector("#playDetailShot"),
  stopDetailShot: document.querySelector("#stopDetailShot"),
  startScreencap: document.querySelector("#startScreencap"),
  startSplit: document.querySelector("#startSplit"),
  cancelSplit: document.querySelector("#cancelSplit"),
  applyScreencap: document.querySelector("#applyScreencap"),
  applySplit: document.querySelector("#applySplit"),
  splitControls: document.querySelector("#splitControls"),
  timelineControlLabel: document.querySelector("#timelineControlLabel"),
  splitSlider: document.querySelector("#splitSlider"),
  splitTime: document.querySelector("#splitTime"),
  nudgeBack: document.querySelector("#nudgeBack"),
  nudgeForward: document.querySelector("#nudgeForward"),
  titleField: document.querySelector("#titleField"),
  notesField: document.querySelector("#notesField"),
  visualField: document.querySelector("#visualField"),
  audioField: document.querySelector("#audioField"),
  actionField: document.querySelector("#actionField"),
  narrativeField: document.querySelector("#narrativeField"),
  filmChat: document.querySelector("#filmChat"),
  filmChatModel: document.querySelector("#filmChatModel"),
  filmChatMessages: document.querySelector("#filmChatMessages"),
  filmChatForm: document.querySelector("#filmChatForm"),
  filmChatQuestion: document.querySelector("#filmChatQuestion"),
  filmChatStatus: document.querySelector("#filmChatStatus"),
  sendFilmChat: document.querySelector("#sendFilmChat"),
  clearFilmChat: document.querySelector("#clearFilmChat"),
  closeFilmChat: document.querySelector("#closeFilmChat"),
  toast: document.querySelector("#toast"),
};

function formatDuration(seconds) {
  const raw = Number(seconds);
  const value = Number.isFinite(raw) ? Math.max(0, raw) : 0;
  const rounded = Math.round(value * 100) / 100;
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded - hours * 3600) / 60);
  const remainingSeconds = rounded - hours * 3600 - minutes * 60;
  const secondsText = remainingSeconds.toFixed(2);
  if (hours) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m ${secondsText.padStart(5, "0")}s`;
  }
  if (minutes) {
    return `${minutes}m ${secondsText.padStart(5, "0")}s`;
  }
  return `${secondsText}s`;
}

function durationColor(seconds) {
  const value = Number(seconds);
  const clamped = Math.max(1, Math.min(6, value));
  const ratio = (clamped - 1) / 5;
  const hue = Math.round(ratio * 120);
  const lightness = Math.round(58 - ratio * 10);
  return `hsl(${hue} 84% ${lightness}%)`;
}

function normalizedMovement(shot) {
  const type = String(shot.camera_movement_type || "").trim().toLowerCase();
  const intensity = String(shot.camera_movement_intensity || "").trim().toLowerCase();
  const confidence = String(shot.camera_movement_confidence || "").trim().toLowerCase();
  return { type, intensity, confidence };
}

function hasCameraMovement(shot) {
  const { type, intensity } = normalizedMovement(shot);
  return type && !["static", "none", "unclear"].includes(type) && intensity !== "none";
}

function cameraMovementColor(shot) {
  const { type, intensity } = normalizedMovement(shot);
  if (["handheld", "shake"].includes(type)) {
    return intensity === "strong" || intensity === "crash" ? "#8a6a1f" : "#5e5130";
  }
  const palette = {
    subtle: "#3a2d1c",
    medium: "#5a3d18",
    strong: "#825316",
    crash: "#b36b12",
  };
  return palette[intensity] || "#4a351e";
}

function cameraMovementLabel(shot) {
  if (!hasCameraMovement(shot)) return "";
  const { type, intensity, confidence } = normalizedMovement(shot);
  const niceType = type.replaceAll("_", " ");
  const parts = [niceType];
  if (intensity && intensity !== "unclear") parts.push(intensity);
  if (confidence) parts.push(`${confidence} confidence`);
  return parts.join(" - ");
}

function formatStartTime(value) {
  const [hours = "00", minutes = "00", seconds = "00"] = String(value).split(":");
  const centiseconds = Number(seconds).toFixed(2).padStart(5, "0");
  return `${hours.padStart(2, "0")}:${minutes.padStart(2, "0")}:${centiseconds}`;
}

function secondsToTimestamp(value) {
  const safeValue = Math.max(0, Number(value) || 0);
  const hours = Math.floor(safeValue / 3600);
  const minutes = Math.floor((safeValue % 3600) / 60);
  const seconds = safeValue - hours * 3600 - minutes * 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${seconds.toFixed(3).padStart(6, "0")}`;
}

function shotTitle(shot) {
  return shot.shot_title || shot.title || "Shot Title Pending";
}

function markManualField(shot, field) {
  if (!shot) return;
  if (!Array.isArray(shot.manual_fields)) shot.manual_fields = [];
  if (!shot.manual_fields.includes(field)) shot.manual_fields.push(field);
}

const DETAIL_FIELDS = [
  "shot_title",
  "visual_description",
  "audio_dialogue",
  "action_camera",
  "camera_movement_type",
  "camera_movement_intensity",
  "camera_movement_confidence",
  "camera_movement_evidence",
  "narrative_function",
  "notes",
];

function blankGeneratedDetails(shot, title = "Title Pending") {
  shot.shot_title = title;
  shot.visual_description = "";
  shot.audio_dialogue = "";
  shot.action_camera = "";
  shot.camera_movement_type = "";
  shot.camera_movement_intensity = "";
  shot.camera_movement_confidence = "";
  shot.camera_movement_evidence = "";
  shot.narrative_function = "";
  shot.notes = "";
  shot.manual_fields = [];
  shot.analysis_stale = true;
}

function copyDetailFields(target, source) {
  for (const field of DETAIL_FIELDS) {
    target[field] = source[field] ?? "";
  }
  target.manual_fields = Array.isArray(source.manual_fields) ? [...source.manual_fields] : [];
  target.analysis_stale = false;
}

function applyAiSplitDetails(target, details) {
  blankGeneratedDetails(target, "Title Pending");
  if (!details || typeof details !== "object") return;
  for (const field of DETAIL_FIELDS) {
    const value = details[field];
    if (typeof value === "string" && value.trim()) {
      target[field] = value.trim();
    }
  }
  target.manual_fields = [];
  target.analysis_stale = !details.shot_title;
}

function memberLabel(shot) {
  const members = Array.isArray(shot.members) ? shot.members : [shot.originalShot ?? shot.shot];
  if (members.length <= 1) return `Shot ${shot.shot} - ${shotTitle(shot)}`;
  return `Shot ${shot.shot} - ${shotTitle(shot)} (source ${members[0]}-${members[members.length - 1]})`;
}

function normalizeOutline(outline) {
  const source = Array.isArray(outline?.sentences) ? outline.sentences : [];
  return {
    sentences: source.map((sentence, index) => ({
      id: sentence.id || makeSentenceId(),
      beat: sentence.beat || `Beat ${index + 1}`,
      title: sentence.title || `Sentence ${index + 1}`,
      idea: sentence.idea || "",
      shotNumbers: normalizeShotNumbers(sentence.shotNumbers || sentence.shots || []),
    })).filter((sentence) => sentence.shotNumbers.length),
  };
}

function normalizeShotNumbers(values) {
  const seen = new Set();
  const available = new Set(state.shots.map((shot) => shot.shot));
  return values.map((value) => Number(value))
    .filter((number) => Number.isInteger(number) && available.has(number) && !seen.has(number) && seen.add(number))
    .sort((a, b) => a - b);
}

function makeSentenceId() {
  return `sentence-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function sentenceLabel(index) {
  return `S${index + 1}`;
}

function sentenceColor(index) {
  const palette = [
    "#45c4b0",
    "#f2c46d",
    "#8aa8ff",
    "#f06f8f",
    "#93d46b",
    "#c48bff",
    "#f29a5c",
    "#5fc7ee",
  ];
  return palette[index % palette.length];
}

function formatShotNumbers(numbers) {
  if (!numbers.length) return "No shots";
  const sorted = [...numbers].sort((a, b) => a - b);
  const ranges = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (const number of sorted.slice(1)) {
    if (number === previous + 1) {
      previous = number;
      continue;
    }
    ranges.push(start === previous ? `#${start}` : `#${start}-#${previous}`);
    start = number;
    previous = number;
  }
  ranges.push(start === previous ? `#${start}` : `#${start}-#${previous}`);
  return ranges.join(", ");
}

function formatCompactNumber(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(number);
}

function visibleDialogue(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const lower = text.toLowerCase();
  if (
    lower.includes("audio transcription pending") ||
    lower.includes("future pass should align") ||
    lower.includes("no clear dialogue/audio available")
  ) {
    return "";
  }
  return text;
}

function clampPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 50;
  return Math.max(0, Math.min(100, number));
}

function normalizeCoverCrop(crop) {
  return {
    x: clampPercent(crop?.x),
    y: clampPercent(crop?.y),
  };
}

function coverPosition(crop) {
  const normalized = normalizeCoverCrop(crop);
  return `${normalized.x}% ${normalized.y}%`;
}

function coverCropMetrics(image) {
  const rect = image.getBoundingClientRect();
  const naturalWidth = image.naturalWidth || rect.width;
  const naturalHeight = image.naturalHeight || rect.height;
  if (!rect.width || !rect.height || !naturalWidth || !naturalHeight) {
    return { overflowX: 0, overflowY: 0 };
  }
  const scale = Math.max(rect.width / naturalWidth, rect.height / naturalHeight);
  return {
    overflowX: Math.max(0, naturalWidth * scale - rect.width),
    overflowY: Math.max(0, naturalHeight * scale - rect.height),
  };
}

function setLocalProjectCoverCrop(projectId, crop) {
  const project = state.projects.find((item) => item.id === projectId);
  if (project) {
    project.coverCrop = normalizeCoverCrop(crop);
  }
}

function renderStudySource(project) {
  const sourceUrl = project?.sourceUrl || project?.channelUrl || "";
  const stats = project?.socialStats || {};
  const statItems = [
    ["Views", stats.viewCount || project?.viewCount],
    ["Likes", stats.likeCount || project?.likeCount],
    ["Comments", stats.commentCount || project?.commentCount],
    ["Reposts", stats.repostCount || project?.repostCount],
    ["Saves", stats.saveCount || project?.saveCount],
  ].map(([label, value]) => {
    const formatted = formatCompactNumber(value);
    return formatted ? `${formatted} ${label.toLowerCase()}` : "";
  }).filter(Boolean);

  els.studySourcePanel.hidden = !project;
  els.openFolderButton.hidden = !project;
  els.sourceLink.hidden = !sourceUrl;
  if (sourceUrl) {
    els.sourceLink.href = sourceUrl;
  } else {
    els.sourceLink.removeAttribute("href");
  }
  els.socialStats.textContent = statItems.join(" / ");

  const comments = Array.isArray(stats.topComments) ? stats.topComments.slice(0, 3) : [];
  els.socialStats.title = comments.length
    ? comments.map((comment) => String(comment.text || comment.content || comment)).join("\n")
    : "";
}

function renderFullVideo(project) {
  const videoUrl = project?.videoUrl || "";
  els.fullVideoPanel.hidden = !videoUrl;
  if (!videoUrl) {
    state.fullVideoOpen = false;
    pauseFullVideo();
    els.fullVideo.removeAttribute("src");
    els.fullVideo.load();
    return;
  }
  els.fullVideoToggle.textContent = state.fullVideoOpen ? "Hide Full Video" : "Watch Full Video";
  els.fullVideoToggle.setAttribute("aria-expanded", String(state.fullVideoOpen));
  els.fullVideoFrame.hidden = !state.fullVideoOpen;
  if (state.fullVideoOpen && !els.fullVideo.src.endsWith(videoUrl)) {
    els.fullVideo.src = videoUrl;
  }
}

function toggleFullVideo() {
  if (!state.project?.videoUrl) return;
  state.fullVideoOpen = !state.fullVideoOpen;
  renderFullVideo(state.project);
}

function pauseFullVideo() {
  if (!els.fullVideo) return;
  els.fullVideo.pause();
}

function sentenceIndexesForShot(shotNumber) {
  return state.outline.sentences
    .map((sentence, index) => sentence.shotNumbers.includes(shotNumber) ? index : -1)
    .filter((index) => index >= 0);
}

function sentenceTitleForDetail(shotNumber) {
  const sentenceIndexes = sentenceIndexesForShot(shotNumber);
  if (!sentenceIndexes.length) {
    return null;
  }
  return sentenceIndexes.map((sentenceIndex) => {
    const sentence = state.outline.sentences[sentenceIndex];
    const title = sentence?.title || `Sentence ${sentenceIndex + 1}`;
    return `${sentenceLabel(sentenceIndex)} - ${title}`;
  }).join(" / ");
}

function cloneForUndo(value) {
  return JSON.parse(JSON.stringify(value));
}

function clearUndoHistory() {
  state.undoStack = [];
  state.undoCaptureKey = null;
  updateUndoButton();
}

function updateUndoButton() {
  if (els.undoEdit) {
    els.undoEdit.disabled = state.undoStack.length === 0;
  }
}

function rememberUndo(label, key = null) {
  if (!state.project) return;
  if (key && state.undoCaptureKey === key) return;
  state.undoStack.push({
    label,
    shots: cloneForUndo(state.shots),
    outline: cloneForUndo(state.outline),
    selected: [...state.selected],
    activeIndex: state.activeIndex,
    dirty: state.dirty,
  });
  state.undoStack = state.undoStack.slice(-25);
  state.undoCaptureKey = key;
  updateUndoButton();
}

function undoLastEdit() {
  const snapshot = state.undoStack.pop();
  if (!snapshot) return;
  stopClip();
  cancelSplitMode();
  state.shots = cloneForUndo(snapshot.shots);
  state.outline = normalizeOutline(snapshot.outline);
  state.selected = new Set(snapshot.selected || []);
  state.activeIndex = snapshot.activeIndex == null ? null : Math.min(snapshot.activeIndex, state.shots.length - 1);
  state.dirty = Boolean(snapshot.dirty);
  state.undoCaptureKey = null;
  els.saveButton.disabled = !state.dirty;
  updateUndoButton();
  render();
  if (state.activeIndex != null && !els.detailView.hidden) {
    syncDetailFields();
  }
  setStatus(`Undid ${snapshot.label}.`);
}

function setStatus(message) {
  els.statusText.textContent = message;
}

function loadLlmSettings() {
  const savedModel = localStorage.getItem("filmStudyModel");
  const settingsVersion = localStorage.getItem("filmStudyModelSettingsVersion");
  const legacyModels = new Set(["qwen-vl-max-latest", "qwen-vl-plus-latest"]);
  els.modelField.value =
    settingsVersion === "omni-v2" && QWEN_VIDEO_MODELS.has(savedModel) && !legacyModels.has(savedModel)
      ? savedModel
      : DEFAULT_QWEN_VIDEO_MODEL;
  localStorage.setItem("filmStudyModel", els.modelField.value);
  localStorage.setItem("filmStudyModelSettingsVersion", "omni-v2");
}

function saveLlmSettings() {
  localStorage.setItem("filmStudyModel", els.modelField.value);
  localStorage.setItem("filmStudyModelSettingsVersion", "omni-v2");
}

function contextStorageKey(projectId) {
  return `filmStudyContext:${projectId}`;
}

function setProjectContext(projectId, value, persistFallback = true) {
  els.filmContextField.value = value || "";
  if (persistFallback && projectId) {
    localStorage.setItem(contextStorageKey(projectId), els.filmContextField.value);
  }
}

function scheduleContextSave() {
  if (!state.project) return;
  localStorage.setItem(contextStorageKey(state.project.id), els.filmContextField.value);
  window.clearTimeout(state.contextSaveTimer);
  state.contextSaveTimer = window.setTimeout(() => saveProjectContext(), 700);
  renderAnalysisControls();
}

async function saveProjectContext() {
  if (!state.project) return;
  window.clearTimeout(state.contextSaveTimer);
  state.contextSaveTimer = null;
  try {
    await fetchJson(`/api/projects/${encodeURIComponent(state.project.id)}/context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userContext: els.filmContextField.value }),
    });
  } catch (error) {
    console.error(error);
    setStatus(readErrorMessage(error, "Could not save your read on the film."));
  }
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function navigationTarget(historyState = window.history.state) {
  if (historyState && ["home", "study", "shot"].includes(historyState.view)) {
    return {
      view: historyState.view,
      projectId: String(historyState.projectId || ""),
      shotNumber: Number(historyState.shotNumber) || null,
    };
  }
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("project") || "";
  const shotNumber = Number(params.get("shot")) || null;
  return {
    view: projectId ? (shotNumber ? "shot" : "study") : "home",
    projectId,
    shotNumber,
  };
}

function navigationUrl(target) {
  const url = new URL(window.location.href);
  url.searchParams.delete("project");
  url.searchParams.delete("shot");
  if (target.projectId) url.searchParams.set("project", target.projectId);
  if (target.view === "shot" && target.shotNumber) {
    url.searchParams.set("shot", String(target.shotNumber));
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

function updateNavigationHistory(target, mode = "push") {
  if (mode === "none") return;
  const method = mode === "replace" ? "replaceState" : "pushState";
  window.history[method](target, "", navigationUrl(target));
}

async function loadProjects() {
  const data = await fetchJson("/api/projects");
  state.projects = data.projects;
  state.folders = Array.isArray(data.folders) ? data.folders : [];
  populateProjectSelect();
  const target = navigationTarget();
  if (target.projectId && state.projects.some((project) => project.id === target.projectId)) {
    await loadProject(target.projectId, {
      historyMode: "replace",
      shotNumber: target.view === "shot" ? target.shotNumber : null,
    });
  } else {
    showHome({ historyMode: "replace" });
  }
}

async function refreshProjectList() {
  const currentId = state.project?.id;
  const data = await fetchJson("/api/projects");
  state.projects = data.projects;
  state.folders = Array.isArray(data.folders) ? data.folders : [];
  populateProjectSelect();
  renderHome();
  if (currentId && state.projects.some((project) => project.id === currentId)) {
    els.projectSelect.value = currentId;
  }
}

function populateProjectSelect() {
  els.projectSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Open film...";
  els.projectSelect.append(placeholder);
  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.name} (${project.shotCount})${project.hasCorrections ? " corrected" : ""}`;
    els.projectSelect.append(option);
  }
}

async function loadProject(projectId, { historyMode = "push", shotNumber = null } = {}) {
  if (!projectId) {
    showHome({ historyMode });
    return;
  }
  const data = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}`);
  state.project = data;
  state.shots = data.shots;
  state.outline = normalizeOutline(data.outline);
  const loadedContext = data.userContext || "";
  state.analyzedContext = data.analysisSession?.hasFullAnalysis && !data.analysisSession?.contextChanged
    ? loadedContext
    : null;
  setProjectContext(data.id, loadedContext);
  if (!loadedContext) {
    localStorage.removeItem(contextStorageKey(data.id));
  }
  localStorage.removeItem("filmStudyContext");
  state.view = "study";
  clearSelection();
  state.activeIndex = null;
  clearUndoHistory();
  closeSentencePopover(false);
  state.dirty = false;
  state.fullVideoOpen = false;
  state.analysisJob = null;
  els.saveButton.disabled = true;
  els.projectSelect.value = data.id;
  els.projectMeta.textContent = `${data.name} - ${data.shots.length} shots`;
  renderStudySource(data);
  renderFullVideo(data);
  setStatus("Overview ready.");
  render();
  renderAnalysisUsage(data.analysisSession?.lastUsage);
  renderAnalysisHistory(data.analysisSession?.analysisHistory);
  const requestedShotIndex = shotNumber == null
    ? -1
    : state.shots.findIndex((shot) => Number(shot.shot) === Number(shotNumber));
  if (requestedShotIndex >= 0) {
    openDetail(requestedShotIndex, { historyMode: "none" });
  }
  const activeShot = state.activeIndex == null ? null : state.shots[state.activeIndex];
  updateNavigationHistory({
    view: activeShot ? "shot" : "study",
    projectId: data.id,
    shotNumber: activeShot ? Number(activeShot.shot) : null,
  }, historyMode);
  await syncAnalysisStatus(data.id);
}

function formatElapsedTime(seconds) {
  return formatDuration(seconds);
}

function formatTokenCount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString() : "0";
}

function analysisPhaseLabel(job) {
  const labels = {
    preparing: "Preparing analysis",
    checking_timeline: "Checking the timeline",
    preparing_batch: "Preparing video batch",
    waiting_api: `Waiting for ${String(job.provider || "the model").replace(/^./, (letter) => letter.toUpperCase())}`,
    streaming: "API connected - receiving response",
    validating: "Validating model response",
    retrying: "Repairing an incomplete response",
    batch_complete: "Batch complete",
    narrative_pass: "Reconciling narrative continuity",
    saving: "Saving analysis",
    complete: "Analysis complete",
    failed: "Analysis failed",
  };
  return labels[job.phase] || "Analyzing film";
}

function renderAnalysisUsage(usage) {
  const value = usage && typeof usage === "object" ? usage : null;
  if (!value || !Number(value.apiCalls || 0) || els.analysisHistoryList?.children.length) {
    els.analysisUsage.hidden = true;
    els.analysisUsage.textContent = "";
    return;
  }
  const parts = [`${value.apiCalls} API ${Number(value.apiCalls) === 1 ? "call" : "calls"}`];
  if (value.tokensReported) {
    parts.push(
      `${formatTokenCount(value.inputTokens)} input + ${formatTokenCount(value.outputTokens)} output = ${formatTokenCount(value.totalTokens)} tokens`
    );
  } else {
    parts.push(value.legacy ? "Token counts were not retained for this earlier run" : "Provider did not return token counts");
  }
  if (value.costUsd != null) {
    const cost = Number(value.costUsd);
    const label = value.costSource === "provider" ? "reported cost" : "estimated cost";
    parts.push(`${label}: $${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)} USD`);
  } else {
    parts.push(value.legacy ? "Earlier-run cost is unavailable" : "Currency cost was not reported");
  }
  els.analysisUsage.textContent = `Latest usage: ${parts.join(" | ")}`;
  els.analysisUsage.hidden = false;
}

function formatRunDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatRunCost(usage) {
  if (usage?.costUsd != null) {
    const cost = Number(usage.costUsd);
    const amount = cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2);
    return `$${amount} USD ${usage.costSource === "provider" ? "reported" : "estimated"}`;
  }
  return usage?.legacy ? "Cost unavailable for this earlier run" : "Cost not reported";
}

function renderAnalysisHistory(history) {
  const runs = Array.isArray(history) ? history : [];
  if (runs.length) {
    els.analysisUsage.hidden = true;
  }
  els.analysisHistoryCount.textContent = runs.length
    ? `${runs.length} ${runs.length === 1 ? "run" : "runs"}`
    : "No runs";
  els.analysisHistoryList.replaceChildren();

  if (!runs.length) {
    const empty = document.createElement("p");
    empty.className = "analysis-history-empty";
    empty.textContent = "Analysis activity will appear here.";
    els.analysisHistoryList.append(empty);
    return;
  }

  const modeLabels = {
    full: "Full film",
    incremental: "Changed shots",
    memory: "Film notes",
    continuity: "Narrative continuity",
    up_to_date: "Already current",
  };
  for (const run of runs) {
    const row = document.createElement("article");
    row.className = `analysis-run is-${run.status || "completed"}`;

    const heading = document.createElement("div");
    heading.className = "analysis-run-heading";
    const model = document.createElement("strong");
    model.textContent = run.model || run.provider || "Analysis model";
    const status = document.createElement("span");
    status.className = "analysis-run-status";
    status.textContent = run.status === "failed" ? "Failed" : "Complete";
    heading.append(model, status);

    const date = document.createElement("p");
    date.className = "analysis-run-date";
    date.textContent = formatRunDate(run.completedAt || run.startedAt);

    const summary = document.createElement("p");
    summary.className = "analysis-run-summary";
    const summaryParts = [
      modeLabels[run.mode] || run.mode || "Analysis",
      run.elapsedSeconds == null ? "Time unavailable" : formatElapsedTime(run.elapsedSeconds),
    ];
    if (run.totalShotCount != null) {
      const analyzed = Number(run.analyzedShotCount || 0);
      summaryParts.push(
        run.mode === "up_to_date"
          ? `${run.totalShotCount} shots checked`
          : `${analyzed} of ${run.totalShotCount} shots analyzed`
      );
    } else if (run.analyzedShotCount != null) {
      summaryParts.push(`${Number(run.analyzedShotCount || 0)} shots analyzed`);
    }
    const detectedCuts = Number(run.cutDetectedCount || 0);
    const appliedCuts = Number(run.cutAppliedCount || 0);
    const pendingCuts = Number(run.cutPendingCount || 0);
    if (detectedCuts) {
      summaryParts.push(
        `${detectedCuts} missing ${detectedCuts === 1 ? "cut" : "cuts"} found, ${appliedCuts} applied`
      );
    }
    if (pendingCuts) {
      summaryParts.push(`${pendingCuts} pending`);
    }
    summary.textContent = summaryParts.join(" | ");

    const usage = run.usage && typeof run.usage === "object" ? run.usage : {};
    const metrics = document.createElement("p");
    metrics.className = "analysis-run-metrics";
    const callCount = Number(usage.apiCalls || 0);
    const metricParts = [
      `${callCount} API ${callCount === 1 ? "call" : "calls"}`,
    ];
    if (usage.tokensReported) {
      metricParts.push(
        `${formatTokenCount(usage.inputTokens)} input + ${formatTokenCount(usage.outputTokens)} output = ${formatTokenCount(usage.totalTokens)} tokens`
      );
    } else {
      metricParts.push(run.legacy ? "Token count unavailable" : "Tokens not reported");
    }
    metricParts.push(formatRunCost(usage));
    metrics.textContent = metricParts.join(" | ");

    row.append(heading, date, summary, metrics);
    const calls = Array.isArray(usage.calls) ? usage.calls : [];
    if (calls.length > 1) {
      const callDetails = document.createElement("details");
      callDetails.className = "analysis-call-details";
      const callSummary = document.createElement("summary");
      callSummary.textContent = "Per-call token breakdown";
      const callList = document.createElement("div");
      callList.className = "analysis-call-list";
      for (const call of calls) {
        const callLine = document.createElement("p");
        callLine.textContent = usage.tokensReported
          ? `Call ${call.number}: ${formatTokenCount(call.inputTokens)} input + ${formatTokenCount(call.outputTokens)} output`
          : `Call ${call.number}: token count not reported`;
        callList.append(callLine);
      }
      callDetails.append(callSummary, callList);
      row.append(callDetails);
    }
    if (run.error || run.status === "failed") {
      const error = document.createElement("p");
      error.className = "analysis-run-error";
      error.textContent = run.error || run.message || "Analysis failed.";
      row.append(error);
    } else if (run.legacy) {
      const note = document.createElement("p");
      note.className = "analysis-run-note";
      note.textContent = "Detailed tracking was not yet enabled for this run.";
      row.append(note);
    }
    els.analysisHistoryList.append(row);
  }
}

function renderAnalysisJob(job) {
  state.analysisJob = job;
  const status = String(job?.status || "idle");
  if (job?.usage) renderAnalysisUsage(job.usage);
  if (status === "idle") {
    els.analysisProgress.hidden = true;
    els.analysisProgress.classList.remove("is-failed", "is-complete");
    return;
  }
  els.analysisProgress.hidden = false;
  els.analysisProgress.classList.toggle("is-failed", status === "failed");
  els.analysisProgress.classList.toggle("is-complete", status === "completed");
  els.analysisPhase.textContent = analysisPhaseLabel(job);
  els.analysisProgressDetail.textContent = job.message || "Analysis is running.";
  els.analysisProgressBar.style.width = `${Math.max(0, Math.min(100, Number(job.progress) || 0))}%`;
  els.analysisElapsed.textContent = formatElapsedTime(job.elapsedSeconds || 0);
  renderAnalysisUsage(job.usage || state.project?.analysisSession?.lastUsage);
  const running = status === "running";
  els.generateDetails.disabled = running;
  els.reprocessVideo.disabled = running || !state.project?.analysisSession?.hasFullAnalysis;
  if (running) {
    els.generateDetails.textContent = "Analyzing...";
  }
}

function stopAnalysisPolling() {
  window.clearTimeout(state.analysisPollTimer);
  window.clearInterval(state.analysisClockTimer);
  state.analysisPollTimer = null;
  state.analysisClockTimer = null;
  state.analysisStartedAt = null;
}

function startAnalysisClock(elapsedSeconds = 0) {
  window.clearInterval(state.analysisClockTimer);
  state.analysisStartedAt = Date.now() - Math.max(0, Number(elapsedSeconds) || 0) * 1000;
  state.analysisClockTimer = window.setInterval(() => {
    if (!state.analysisStartedAt || state.analysisJob?.status !== "running") return;
    const elapsed = Math.floor((Date.now() - state.analysisStartedAt) / 1000);
    els.analysisElapsed.textContent = formatElapsedTime(elapsed);
  }, 1000);
}

async function pollAnalysisStatus(projectId) {
  window.clearTimeout(state.analysisPollTimer);
  if (!state.project || state.project.id !== projectId) return;
  try {
    const job = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}/analysis-status`);
    if (!state.project || state.project.id !== projectId) return;
    renderAnalysisJob(job);
    if (job.status === "running") {
      if (!state.analysisClockTimer) startAnalysisClock(job.elapsedSeconds);
      state.analysisPollTimer = window.setTimeout(() => pollAnalysisStatus(projectId), 1200);
    } else {
      window.clearInterval(state.analysisClockTimer);
      state.analysisClockTimer = null;
    }
  } catch (error) {
    console.error(error);
    if (state.project?.id === projectId && state.analysisJob?.status === "running") {
      els.analysisProgressDetail.textContent = "The analysis request is still open; reconnecting to its status...";
      state.analysisPollTimer = window.setTimeout(() => pollAnalysisStatus(projectId), 1800);
    }
  }
}

async function syncAnalysisStatus(projectId) {
  stopAnalysisPolling();
  await pollAnalysisStatus(projectId);
}

function renderAnalysisControls() {
  if (!state.project) return;
  const session = state.project.analysisSession || {};
  const includedCount = state.shots.filter((shot) => !shot.analysis_excluded).length;
  const excludedCount = state.shots.length - includedCount;
  const locallyChanged = state.shots.filter(
    (shot) => shot.analysis_stale && !shot.analysis_excluded
  ).length;
  const changedCount = Math.max(Number(session.changedShotCount || 0), locallyChanged);
  const hasFullAnalysis = Boolean(session.hasFullAnalysis);
  const needsNarrativeContinuity = Boolean(session.needsNarrativeContinuity);
  const needsAiCutUpgrade = Boolean(session.needsAiCutUpgrade);
  const needsSentenceOutline = Boolean(session.needsSentenceOutline);
  const analysisRunning = state.analysisJob?.status === "running";
  els.analysisScopeStatus.textContent = excludedCount
    ? `Analysis scope: ${includedCount} included, ${excludedCount} excluded.`
    : `Analysis scope: complete film, ${includedCount} shots.`;
  els.generateDetails.disabled = includedCount === 0;
  els.askThisFilm.disabled = analysisRunning || !hasFullAnalysis || Boolean(session.scopeChanged);
  els.exportForAi.disabled = includedCount === 0;
  const contextChanged = Boolean(session.contextChanged)
    || (state.analyzedContext != null && els.filmContextField.value.trim() !== state.analyzedContext.trim());
  if (analysisRunning) {
    els.generateDetails.textContent = "Analyzing...";
    els.generateDetails.disabled = true;
    els.reprocessVideo.disabled = true;
    els.analysisStatus.textContent = "Live progress appears below. You can leave this study and return while the server continues.";
    return;
  }
  els.generateDetails.textContent = hasFullAnalysis
    ? (
      needsAiCutUpgrade
        ? "Upgrade Analysis"
        : (needsNarrativeContinuity && !changedCount && !contextChanged ? "Repair Narrative Context" : "Update Analysis")
    )
    : "Analyze Film";
  els.generateDetails.disabled = includedCount === 0;
  els.reprocessVideo.disabled = !hasFullAnalysis;
  if (!hasFullAnalysis) {
    els.analysisStatus.textContent = includedCount
      ? `Ready to watch and listen to the ${excludedCount ? "included part" : "complete film"}.`
      : "Include at least one shot before analysis.";
    return;
  }
  if (session.scopeChanged) {
    els.analysisStatus.textContent = "The analysis scope changed. Qwen will rebuild film memory from the included shots.";
    return;
  }
  const model = session.model || "saved film memory";
  if (needsAiCutUpgrade) {
    els.analysisStatus.textContent = "Ready to rewatch the film once, audit every possible cut, and organize the shots into filmic sentences.";
  } else if (changedCount) {
    els.analysisStatus.textContent = `${changedCount} changed ${changedCount === 1 ? "shot" : "shots"} ready to update with ${model}.`;
  } else if (contextChanged) {
    els.analysisStatus.textContent = `Updated film notes are ready to reconsider with ${model}; the video will not be resent.`;
  } else if (needsNarrativeContinuity) {
    els.analysisStatus.textContent = "Narrative context can be repaired across all existing shots without resending the video.";
  } else if (needsSentenceOutline) {
    els.analysisStatus.textContent = "The existing analysis can organize these shots into filmic sentences without resending the video.";
  } else {
    els.analysisStatus.textContent = `Film memory is current with ${model}.`;
  }
}

function showHome({ historyMode = "push" } = {}) {
  closeFilmChat();
  stopAnalysisPolling();
  stopClip();
  pauseFullVideo();
  closeDetailIfOpen();
  closeSentencePopover(false);
  state.view = "home";
  state.project = null;
  state.shots = [];
  state.outline = { sentences: [] };
  state.analyzedContext = null;
  state.analysisJob = null;
  setProjectContext("", "", false);
  clearSelection();
  clearUndoHistory();
  state.editMode = false;
  renderStudySource(null);
  renderFullVideo(null);
  els.projectSelect.value = "";
  els.projectMeta.textContent = `${state.projects.length} films`;
  render();
  updateNavigationHistory({ view: "home", projectId: "", shotNumber: null }, historyMode);
}

function render() {
  const inStudy = state.view === "study";
  els.homeView.hidden = inStudy;
  els.studyView.hidden = !inStudy;
  els.homeButton.hidden = !inStudy;
  els.editToggle.hidden = !inStudy;
  els.saveButton.hidden = !inStudy;
  els.editPanel.hidden = !inStudy || !state.editMode;
  els.editHelp.hidden = !inStudy || !state.editMode;
  els.editToggle.classList.toggle("is-active", state.editMode);
  els.editToggle.textContent = state.editMode ? "Viewing + Editing" : "Edit";
  updateUndoButton();
  if (inStudy) {
    renderAnalysisControls();
    renderSelection();
    renderGrid();
  } else {
    renderHome();
  }
}

function renderHome() {
  const fragment = document.createDocumentFragment();
  els.libraryCount.textContent = `${state.projects.length} ${state.projects.length === 1 ? "film" : "films"} · ${state.folders.length} ${state.folders.length === 1 ? "folder" : "folders"}`;
  if (!state.projects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-library";
    empty.textContent = state.folders.length ? "Drop films into a folder to begin." : "No film breakdowns yet.";
    fragment.append(empty);
  }
  const tree = buildProjectTree(state.projects, state.folders);
  for (const node of tree.children.values()) {
    fragment.append(renderProjectGroup(node));
  }
  if (state.projects.length || state.folders.length) {
    const section = document.createElement("section");
    section.className = "film-folder";
    attachFolderDropTarget(section, []);
    const heading = document.createElement("header");
    heading.className = "film-folder-header";
    const label = document.createElement("div");
    label.className = "film-folder-label";
    const title = document.createElement("h2");
    title.textContent = "Ungrouped";
    const count = document.createElement("span");
    count.textContent = `${tree.projects.length} ${tree.projects.length === 1 ? "study" : "studies"}`;
    label.append(title, count);
    heading.append(label);
    const grid = document.createElement("div");
    grid.className = "film-grid-row";
    for (const project of tree.projects) {
      grid.append(createFilmCard(project));
    }
    if (!tree.projects.length) {
      const empty = document.createElement("div");
      empty.className = "folder-empty";
      empty.textContent = "No ungrouped films";
      grid.append(empty);
    }
    section.append(heading, grid);
    fragment.append(section);
  }
  els.filmGrid.replaceChildren(fragment);
}

function buildProjectTree(projects, folders = []) {
  const root = { name: "", path: [], children: new Map(), projects: [] };
  function ensurePath(path) {
    let node = root;
    for (const part of path) {
      if (!node.children.has(part)) {
        node.children.set(part, { name: part, path: [...node.path, part], children: new Map(), projects: [] });
      }
      node = node.children.get(part);
    }
    return node;
  }
  for (const folder of folders) {
    ensurePath(Array.isArray(folder) ? folder.filter(Boolean) : []);
  }
  for (const project of projects) {
    const path = Array.isArray(project.groupPath) ? project.groupPath.filter(Boolean) : [];
    const node = ensurePath(path);
    node.projects.push(project);
  }
  return root;
}

function renderProjectGroup(node) {
  const section = document.createElement("section");
  section.className = "film-folder";
  attachFolderDropTarget(section, node.path);
  const pathKey = folderPathKey(node.path);
  const isHidden = state.hiddenFolders.has(pathKey);
  section.classList.toggle("is-collapsed", isHidden);
  const heading = document.createElement("header");
  heading.className = "film-folder-header";

  const label = document.createElement("div");
  label.className = "film-folder-label";
  const title = document.createElement("h2");
  title.textContent = node.path.join(" / ");
  const count = document.createElement("span");
  const childCount = countProjectsInNode(node);
  count.textContent = `${childCount} ${childCount === 1 ? "study" : "studies"}`;
  label.append(title, count);

  const actions = document.createElement("div");
  actions.className = "film-folder-actions";
  const toggleButton = document.createElement("button");
  toggleButton.type = "button";
  toggleButton.className = "folder-action-button";
  toggleButton.textContent = isHidden ? "Show thumbnails" : "Hide thumbnails";
  toggleButton.addEventListener("click", () => toggleFolderVisibility(node.path));

  const menu = document.createElement("details");
  menu.className = "folder-actions-menu";
  const menuSummary = document.createElement("summary");
  menuSummary.setAttribute("aria-label", `Manage ${node.path.join(" / ")}`);
  menuSummary.textContent = "...";
  const menuPanel = document.createElement("div");
  menuPanel.className = "folder-actions-panel";
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.textContent = "New subfolder";
  addButton.addEventListener("click", () => createFolder(node.path));
  const renameButton = document.createElement("button");
  renameButton.type = "button";
  renameButton.textContent = "Rename";
  renameButton.addEventListener("click", () => renameFolder(node));
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "delete-folder-button";
  deleteButton.textContent = "Delete folder";
  deleteButton.addEventListener("click", () => deleteFolder(node));
  menuPanel.append(addButton, renameButton, deleteButton);
  menu.append(menuSummary, menuPanel);
  actions.append(toggleButton, menu);
  heading.append(label, actions);
  section.append(heading);

  if (isHidden) return section;

  for (const child of node.children.values()) {
    section.append(renderProjectGroup(child));
  }

  if (node.projects.length) {
    const grid = document.createElement("div");
    grid.className = "film-grid-row";
    for (const project of node.projects) {
      grid.append(createFilmCard(project));
    }
    section.append(grid);
  } else if (!node.children.size) {
    const empty = document.createElement("div");
    empty.className = "folder-empty";
    empty.textContent = "Empty folder";
    section.append(empty);
  }
  return section;
}

function folderPathKey(path) {
  return Array.isArray(path) ? path.join("\u001f") : "";
}

function folderParts(value) {
  return String(value || "").split(/[\\/]+/).map((part) => part.trim()).filter(Boolean);
}

function attachFolderDropTarget(element, path) {
  element.dataset.folderPath = folderPathKey(path);
  element.addEventListener("dragover", (event) => {
    if (!state.dragProjectId) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    for (const target of els.filmGrid.querySelectorAll(".film-folder.is-film-drop-target")) {
      if (target !== element) target.classList.remove("is-film-drop-target");
    }
    element.classList.add("is-film-drop-target");
  });
  element.addEventListener("dragleave", (event) => {
    if (event.relatedTarget && element.contains(event.relatedTarget)) return;
    element.classList.remove("is-film-drop-target");
  });
  element.addEventListener("drop", async (event) => {
    if (!state.dragProjectId) return;
    event.preventDefault();
    event.stopPropagation();
    element.classList.remove("is-film-drop-target");
    const project = state.projects.find((item) => item.id === state.dragProjectId);
    state.dragProjectId = null;
    if (!project || folderPathKey(project.groupPath) === folderPathKey(path)) return;
    await updateProjectMetadata(project.id, { groupPath: path }, {
      status: path.length ? `Moved ${project.name} to ${path.join(" / ")}.` : `Moved ${project.name} to Ungrouped.`,
    });
  });
}

async function createFolder(parentPath = []) {
  const answer = window.prompt(parentPath.length ? `New folder inside ${parentPath.join(" / ")}` : "New folder name");
  if (answer == null) return;
  const names = folderParts(answer);
  if (!names.length) {
    setUploadStatus("Enter a folder name.");
    return;
  }
  const path = [...parentPath, ...names];
  try {
    await fetchJson("/api/folders/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    await refreshProjectList();
    setUploadStatus(`Created ${path.join(" / ")}.`);
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not create that folder."));
  }
}

async function renameFolder(node) {
  const currentName = node.path.at(-1) || "";
  const answer = window.prompt("Rename folder", currentName);
  if (answer == null) return;
  const names = folderParts(answer);
  if (names.length !== 1) {
    setUploadStatus("Enter one folder name.");
    return;
  }
  const newPath = [...node.path.slice(0, -1), names[0]];
  try {
    await fetchJson("/api/folders/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: node.path, newPath }),
    });
    state.hiddenFolders.clear();
    await refreshProjectList();
    setUploadStatus(`Renamed folder to ${newPath.join(" / ")}.`);
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not rename that folder."));
  }
}

function toggleFolderVisibility(path) {
  const key = folderPathKey(path);
  if (state.hiddenFolders.has(key)) {
    state.hiddenFolders.delete(key);
  } else {
    state.hiddenFolders.add(key);
  }
  renderHome();
}

function countProjectsInNode(node) {
  let total = node.projects.length;
  for (const child of node.children.values()) {
    total += countProjectsInNode(child);
  }
  return total;
}

function collectProjectsInNode(node) {
  const projects = [...node.projects];
  for (const child of node.children.values()) {
    projects.push(...collectProjectsInNode(child));
  }
  return projects;
}

function startCoverCropEdit(project) {
  state.coverCropEdit = {
    projectId: project.id,
    originalCrop: normalizeCoverCrop(project.coverCrop),
  };
  setUploadStatus("Drag the cover image to reframe it, then choose Done.");
  renderHome();
}

function finishCoverCropEdit() {
  state.coverCropEdit = null;
  state.coverCropDrag = null;
  setUploadStatus("Cover crop saved.");
  renderHome();
}

async function resetCoverCrop(project) {
  const crop = { x: 50, y: 50 };
  setLocalProjectCoverCrop(project.id, crop);
  await updateProjectMetadata(project.id, { coverCrop: crop }, { status: "Cover crop centered." });
}

function beginCoverCropDrag(event, project, image) {
  if (state.coverCropEdit?.projectId !== project.id) return;
  event.preventDefault();
  event.stopPropagation();
  state.coverCropDrag = {
    projectId: project.id,
    image,
    startX: event.clientX,
    startY: event.clientY,
    crop: normalizeCoverCrop(project.coverCrop),
    metrics: coverCropMetrics(image),
  };
  image.setPointerCapture?.(event.pointerId);
}

function updateCoverCropDrag(event) {
  const drag = state.coverCropDrag;
  if (!drag) return;
  event.preventDefault();
  const dx = event.clientX - drag.startX;
  const dy = event.clientY - drag.startY;
  const nextCrop = { ...drag.crop };
  if (drag.metrics.overflowX > 1) {
    nextCrop.x = clampPercent(drag.crop.x - (dx * 100) / drag.metrics.overflowX);
  }
  if (drag.metrics.overflowY > 1) {
    nextCrop.y = clampPercent(drag.crop.y - (dy * 100) / drag.metrics.overflowY);
  }
  setLocalProjectCoverCrop(drag.projectId, nextCrop);
  drag.image.style.objectPosition = coverPosition(nextCrop);
}

function endCoverCropDrag() {
  const drag = state.coverCropDrag;
  if (!drag) return;
  state.coverCropDrag = null;
  const project = state.projects.find((item) => item.id === drag.projectId);
  const crop = normalizeCoverCrop(project?.coverCrop);
  updateProjectMetadata(drag.projectId, { coverCrop: crop }, { status: "Cover crop saved." });
}

function createFilmCard(project) {
  const card = document.createElement("article");
  card.className = "film-card";
  const cropIsActive = state.coverCropEdit?.projectId === project.id;
  card.classList.toggle("is-cropping", cropIsActive);
  card.draggable = !cropIsActive;
  card.addEventListener("dragstart", (event) => {
    if (cropIsActive || event.target.closest("input, select, textarea, details")) {
      event.preventDefault();
      return;
    }
    state.dragProjectId = project.id;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", project.id);
    window.setTimeout(() => card.classList.add("is-dragging"), 0);
  });
  card.addEventListener("dragend", () => {
    state.dragProjectId = null;
    card.classList.remove("is-dragging");
    for (const target of els.filmGrid.querySelectorAll(".film-folder.is-film-drop-target")) {
      target.classList.remove("is-film-drop-target");
    }
  });

  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.className = "film-open-button";
  openButton.addEventListener("click", (event) => {
    if (state.coverCropEdit?.projectId === project.id) {
      event.preventDefault();
      return;
    }
    loadProject(project.id);
  });

  const poster = document.createElement("div");
  poster.className = "film-poster";
  if (project.coverUrl) {
    const image = document.createElement("img");
    image.src = project.coverUrl;
    image.alt = `${project.name} screenshot`;
    image.style.objectPosition = coverPosition(project.coverCrop);
    image.addEventListener("pointerdown", (event) => beginCoverCropDrag(event, project, image));
    poster.append(image);
  } else {
    const fallback = document.createElement("span");
    fallback.textContent = project.name.slice(0, 1).toUpperCase();
    poster.append(fallback);
  }

  const copy = document.createElement("div");
  copy.className = "film-card-copy";
  copy.addEventListener("click", (event) => {
    if (event.target.closest("button, input, select, textarea")) return;
    loadProject(project.id);
  });
  const title = document.createElement("button");
  title.type = "button";
  title.className = "film-title film-title-button";
  title.textContent = project.name;
  title.title = "Edit film title";
  title.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    beginFilmTitleEdit(project, title);
  });
  const meta = document.createElement("div");
  meta.className = "film-meta";
  const metaParts = [`${project.shotCount} shots${project.hasCorrections ? " - corrected" : ""}`];
  if (project.channelRank) {
    const views = Number(project.viewCount || 0).toLocaleString();
    metaParts.push(`#${project.channelRank} on ${project.channelTitle || "channel"}${views !== "0" ? ` - ${views} views` : ""}`);
  }
  meta.textContent = metaParts.join(" | ");
  copy.append(title, meta);
  openButton.append(poster);

  const controls = document.createElement("div");
  controls.className = "film-card-controls";
  controls.addEventListener("click", (event) => event.stopPropagation());

  const groupLabel = document.createElement("label");
  groupLabel.textContent = "Folder";
  const groupInput = document.createElement("input");
  groupInput.type = "text";
  groupInput.value = Array.isArray(project.groupPath) ? project.groupPath.join(" / ") : "";
  groupInput.placeholder = "Channel / Series";
  groupInput.addEventListener("change", () => updateProjectMetadata(project.id, {
    groupPath: groupInput.value.split(/[\\/]+/).map((part) => part.trim()).filter(Boolean),
  }));
  groupLabel.append(groupInput);

  const coverLabel = document.createElement("label");
  coverLabel.textContent = "Cover";
  const coverSelect = document.createElement("select");
  const options = Array.isArray(project.screenshotOptions) ? project.screenshotOptions : [];
  for (const option of options) {
    const item = document.createElement("option");
    item.value = String(option.shot);
    item.textContent = `#${option.shot} - ${option.title || "Shot"}`;
    coverSelect.append(item);
  }
  if (project.coverShot) {
    coverSelect.value = String(project.coverShot);
  }
  coverSelect.disabled = !options.length;
  coverSelect.addEventListener("change", () => updateProjectMetadata(project.id, {
    coverShot: coverSelect.value,
    coverCrop: { x: 50, y: 50 },
  }));
  coverLabel.append(coverSelect);

  controls.append(groupLabel, coverLabel);

  const cropButton = document.createElement("button");
  cropButton.type = "button";
  cropButton.textContent = cropIsActive ? "Finish Crop" : "Adjust Crop";
  cropButton.disabled = !project.coverUrl;
  cropButton.addEventListener("click", () => {
    if (cropIsActive) {
      finishCoverCropEdit();
    } else {
      startCoverCropEdit(project);
    }
  });

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "delete-film-button";
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", () => deleteProject(project));

  const actions = document.createElement("details");
  actions.className = "film-card-actions";
  actions.addEventListener("click", (event) => event.stopPropagation());
  actions.addEventListener("toggle", () => {
    if (!actions.open) return;
    for (const other of els.filmGrid.querySelectorAll(".film-card-actions[open]")) {
      if (other !== actions) other.open = false;
    }
  });
  const summary = document.createElement("summary");
  summary.setAttribute("aria-label", `Manage ${project.name}`);
  summary.textContent = "...";
  const actionPanel = document.createElement("div");
  actionPanel.className = "film-action-panel";
  actionPanel.append(controls, cropButton, deleteButton);
  actions.append(summary, actionPanel);

  if (cropIsActive) {
    const cropTools = document.createElement("div");
    cropTools.className = "film-crop-tools";
    const hint = document.createElement("span");
    hint.textContent = "Drag cover";
    const centerButton = document.createElement("button");
    centerButton.type = "button";
    centerButton.textContent = "Center";
    centerButton.addEventListener("click", (event) => {
      event.stopPropagation();
      resetCoverCrop(project);
    });
    const doneButton = document.createElement("button");
    doneButton.type = "button";
    doneButton.textContent = "Done";
    doneButton.addEventListener("click", (event) => {
      event.stopPropagation();
      finishCoverCropEdit();
    });
    cropTools.append(hint, centerButton, doneButton);
    card.append(cropTools);
  }

  card.append(openButton, copy, actions);
  return card;
}

function beginFilmTitleEdit(project, titleButton) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "film-title-input";
  input.value = project.name;
  input.maxLength = 180;
  input.setAttribute("aria-label", `Edit title for ${project.name}`);
  titleButton.replaceWith(input);
  input.focus();
  input.select();
  let finished = false;

  async function finish(save) {
    if (finished) return;
    finished = true;
    const value = input.value.trim();
    if (!save || !value || value === project.name) {
      renderHome();
      return;
    }
    await updateProjectMetadata(project.id, { title: value }, { status: `Renamed film to ${value}.` });
  }

  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("dragstart", (event) => event.preventDefault());
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
}

async function updateProjectMetadata(projectId, metadata, options = {}) {
  try {
    await fetchJson(`/api/projects/${encodeURIComponent(projectId)}/metadata`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata),
    });
    await refreshProjectList();
    setUploadStatus(options.status || "Library updated.");
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not update that study."));
  }
}

async function deleteProject(project) {
  const confirmed = window.confirm(`Delete "${project.name}"? This removes the study from the library.`);
  if (!confirmed) return;
  setUploadStatus(`Deleting ${project.name}...`);
  try {
    await fetchJson(`/api/projects/${encodeURIComponent(project.id)}/delete`, {
      method: "POST",
    });
    if (state.project?.id === project.id) showHome();
    await refreshProjectList();
    setUploadStatus(`${project.name} deleted.`);
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not delete that study."));
  }
}

async function deleteFolder(node) {
  const projects = collectProjectsInNode(node);
  const folderName = node.path.join(" / ");
  const contents = projects.length
    ? ` and ${projects.length} ${projects.length === 1 ? "study" : "studies"} inside it`
    : (node.children.size ? " and all of its subfolders" : "");
  const confirmed = window.confirm(
    `Delete folder "${folderName}"${contents}? This cannot be undone.`
  );
  if (!confirmed) return;
  setUploadStatus(`Deleting ${folderName}...`);
  try {
    await fetchJson("/api/folders/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: node.path }),
    });
    if (state.project && projects.some((project) => project.id === state.project.id)) {
      showHome();
    }
    state.hiddenFolders.delete(folderPathKey(node.path));
    await refreshProjectList();
    setUploadStatus(`${folderName} deleted.`);
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not delete that folder."));
  }
}

function renderSelection() {
  const selected = [...state.selected].sort((a, b) => a - b);
  els.selectionCount.textContent = `${selected.length} selected`;
  if (!selected.length) {
    els.selectionRange.textContent = "Select adjacent shots to combine or link as a sentence.";
  } else {
    els.selectionRange.textContent = selected.map((index) => `#${state.shots[index].shot}`).join(", ");
  }
  const adjacent = selected.length >= 2 && selected.every((value, index) => index === 0 || value === selected[index - 1] + 1);
  els.combineSelected.disabled = !adjacent;
  els.linkSentence.disabled = !adjacent;
  els.removeFromSentence.disabled = !selected.some(
    (index) => sentenceIndexesForShot(state.shots[index]?.shot).length > 0
  );
  els.combineWithNext.disabled = selected.length !== 1 || selected[0] >= state.shots.length - 1;
  els.excludeSelected.disabled = !selected.length
    || selected.every((index) => state.shots[index]?.analysis_excluded);
  els.includeSelected.disabled = !selected.length
    || selected.every((index) => !state.shots[index]?.analysis_excluded);
  els.includeAllShots.disabled = !state.shots.some((shot) => shot.analysis_excluded);
  els.useSelectedAnalysis.disabled = !selected.length;
}

function renderGrid() {
  stopClip();
  const fragment = document.createDocumentFragment();
  const primarySentenceByShot = primarySentenceMap();
  let pendingUnlinked = [];

  function flushUnlinked() {
    if (!pendingUnlinked.length) return;
    const row = document.createElement("div");
    row.className = "shot-run";
    for (const item of pendingUnlinked) {
      row.append(createShotCard(item.shot, item.index));
    }
    fragment.append(row);
    pendingUnlinked = [];
  }

  for (let index = 0; index < state.shots.length; index += 1) {
    const shot = state.shots[index];
    const sentenceIndex = primarySentenceByShot.get(shot.shot);
    if (sentenceIndex == null) {
      pendingUnlinked.push({ shot, index });
      continue;
    }
    const sentence = state.outline.sentences[sentenceIndex];
    const sentenceShots = sentence.shotNumbers
      .map((number) => {
        const shotIndex = state.shots.findIndex((candidate) => candidate.shot === number);
        return shotIndex >= 0 ? { shot: state.shots[shotIndex], index: shotIndex } : null;
      })
      .filter(Boolean);
    const firstIndex = Math.min(...sentenceShots.map((item) => item.index));
    if (index !== firstIndex) continue;

    flushUnlinked();
    fragment.append(createSentenceGroup(sentence, sentenceIndex, sentenceShots));
  }
  flushUnlinked();
  els.shotGrid.replaceChildren(fragment);
}

function primarySentenceMap() {
  const map = new Map();
  state.outline.sentences.forEach((sentence, sentenceIndex) => {
    sentence.shotNumbers.forEach((shotNumber) => {
      if (!map.has(shotNumber)) map.set(shotNumber, sentenceIndex);
    });
  });
  return map;
}

function draggedShotIndexesFor(index) {
  const selected = [...state.selected].sort((a, b) => a - b);
  if (selected.includes(index)) {
    return selected;
  }
  return [index];
}

function startShotDrag(index, event) {
  if (!state.editMode) {
    event.preventDefault();
    return;
  }
  state.dragShotIndexes = draggedShotIndexesFor(index);
  event.currentTarget.classList.add("is-dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", state.dragShotIndexes.join(","));
  setStatus(`Drag ${state.dragShotIndexes.length === 1 ? "this shot" : `${state.dragShotIndexes.length} shots`} onto a sentence.`);
}

function finishShotDrag(event) {
  event.currentTarget.classList.remove("is-dragging");
  state.dragShotIndexes = [];
  for (const group of els.shotGrid.querySelectorAll(".sentence-shot-group.is-drop-target")) {
    group.classList.remove("is-drop-target");
  }
}

function canDropShotsIntoSentence(sentenceIndex) {
  return state.editMode && state.dragShotIndexes.length > 0 && Boolean(state.outline.sentences[sentenceIndex]);
}

function addDraggedShotsToSentence(sentenceIndex) {
  const target = state.outline.sentences[sentenceIndex];
  if (!target || !state.dragShotIndexes.length) return;
  const shotNumbers = state.dragShotIndexes
    .map((shotIndex) => state.shots[shotIndex]?.shot)
    .filter((shotNumber) => Number.isInteger(shotNumber));
  if (!shotNumbers.length) return;

  const nextOutline = cloneForUndo(state.outline);
  const nextTarget = nextOutline.sentences[sentenceIndex];
  const targetId = nextTarget.id;
  for (const sentence of nextOutline.sentences) {
    if (sentence.id === targetId) continue;
    sentence.shotNumbers = normalizeShotNumbers(sentence.shotNumbers.filter((shotNumber) => !shotNumbers.includes(shotNumber)));
  }
  nextTarget.shotNumbers = normalizeShotNumbers([...nextTarget.shotNumbers, ...shotNumbers]);
  nextOutline.sentences = nextOutline.sentences.filter((sentence) => sentence.id === targetId || sentence.shotNumbers.length > 0);
  const before = JSON.stringify(state.outline);
  const after = JSON.stringify(nextOutline);
  if (before === after) {
    setStatus("Those shots are already in that sentence.");
    return;
  }

  rememberUndo("sentence drag-and-drop");
  state.outline = normalizeOutline(nextOutline);
  state.selected = new Set(state.dragShotIndexes);
  state.selectionAnchorIndex = state.dragShotIndexes[0] ?? null;
  markDirty(`Moved ${formatShotNumbers(shotNumbers)} into ${target.title || "that sentence"}. Save corrections to keep it.`);
  closeSentencePopover(false);
  render();
}

function createSentenceGroup(sentence, sentenceIndex, sentenceShots) {
  const group = document.createElement("section");
  group.className = "sentence-shot-group";
  group.dataset.sentenceIndex = String(sentenceIndex);
  group.style.setProperty("--sentence-color", sentenceColor(sentenceIndex));
  group.addEventListener("click", (event) => {
    if (event.target.closest(".shot-card, button, input, textarea, select, video")) return;
    event.stopPropagation();
    openSentencePopover(sentenceIndex, event.clientX, event.clientY);
  });
  group.addEventListener("dragover", (event) => {
    if (!canDropShotsIntoSentence(sentenceIndex)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    group.classList.add("is-drop-target");
  });
  group.addEventListener("dragleave", (event) => {
    if (!group.contains(event.relatedTarget)) {
      group.classList.remove("is-drop-target");
    }
  });
  group.addEventListener("drop", (event) => {
    if (!canDropShotsIntoSentence(sentenceIndex)) return;
    event.preventDefault();
    event.stopPropagation();
    group.classList.remove("is-drop-target");
    addDraggedShotsToSentence(sentenceIndex);
  });

  const header = document.createElement("div");
  header.className = "sentence-shot-header";
  const label = document.createElement("span");
  label.className = "sentence-shot-label";
  label.textContent = sentenceLabel(sentenceIndex);
  const title = document.createElement("strong");
  title.textContent = sentence.title || `Sentence ${sentenceIndex + 1}`;
  const duration = document.createElement("span");
  duration.className = "sentence-shot-duration";
  const sentenceDuration = sentenceShots.reduce((total, item) => total + Number(item.shot.duration_seconds || 0), 0);
  duration.textContent = formatDuration(sentenceDuration);
  const meta = document.createElement("span");
  meta.textContent = `${sentence.beat || "Beat"} - ${formatShotNumbers(sentence.shotNumbers)}`;
  header.append(label, title, duration, meta);

  const row = document.createElement("div");
  row.className = "sentence-shot-row";
  for (const item of sentenceShots) {
    row.append(createShotCard(item.shot, item.index));
  }

  group.append(header, row);
  return group;
}

function createShotCard(shot, index) {
  const card = document.createElement("article");
  card.className = "shot-card";
  card.dataset.shotIndex = String(index);
  card.draggable = state.editMode;
  card.classList.toggle("is-selected", state.selected.has(index));
  card.classList.toggle("is-combined", Array.isArray(shot.members) && shot.members.length > 1);
  card.classList.toggle("is-analysis-excluded", Boolean(shot.analysis_excluded));
  card.classList.toggle("has-camera-movement", hasCameraMovement(shot));
  if (hasCameraMovement(shot)) {
    card.style.setProperty("--movement-color", cameraMovementColor(shot));
  }
  const sentenceIndexes = sentenceIndexesForShot(shot.shot);
  card.classList.toggle("is-linked", sentenceIndexes.length > 0);
  if (sentenceIndexes.length) {
    card.style.setProperty("--sentence-color", sentenceColor(sentenceIndexes[0]));
  }
  card.addEventListener("dragstart", (event) => startShotDrag(index, event));
  card.addEventListener("dragend", (event) => finishShotDrag(event));

  const button = document.createElement("div");
  button.className = "card-main";
  button.setAttribute("role", "button");
  button.tabIndex = 0;
  button.addEventListener("click", (event) => onShotCardClick(index, event));
  button.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onShotCardClick(index, event);
    }
  });

  const thumbWrap = document.createElement("div");
  thumbWrap.className = "thumb-wrap";
  const img = document.createElement("img");
  img.src = shot.screenshotUrl;
  img.alt = `${memberLabel(shot)} screenshot`;
  thumbWrap.append(img);
  if (shot.analysis_excluded) {
    const excludedBadge = document.createElement("span");
    excludedBadge.className = "analysis-excluded-badge";
    excludedBadge.textContent = "Excluded";
    thumbWrap.append(excludedBadge);
  }

  const info = document.createElement("div");
  info.className = "shot-info";
  const title = document.createElement("div");
  title.className = "shot-title";
  const number = document.createElement("span");
    number.className = "shot-number-text";
    number.textContent = `#${shot.shot}`;
    const titleText = document.createElement("span");
    titleText.className = "editable-shot-title";
    titleText.title = "Click to edit title";
    titleText.textContent = ` - ${shotTitle(shot)}`;
    titleText.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      startOverviewTitleEdit(index, titleText);
    });
    title.append(number, titleText);
  const time = document.createElement("div");
  time.className = "shot-time";
  const start = document.createElement("span");
  start.className = "shot-start";
  start.textContent = formatStartTime(shot.start);
  const duration = document.createElement("span");
  duration.className = "duration-chip";
  duration.style.setProperty("--duration-color", durationColor(shot.duration_seconds));
  duration.textContent = formatDuration(shot.duration_seconds);
  time.append(start, duration);
  info.append(title, time);
  const dialogueText = visibleDialogue(shot.audio_dialogue);
  if (dialogueText) {
    const dialogue = document.createElement("div");
    dialogue.className = "shot-dialogue";
    dialogue.textContent = dialogueText;
    info.append(dialogue);
  }
  const movementLabel = cameraMovementLabel(shot);
  if (movementLabel) {
    const movement = document.createElement("div");
    movement.className = "movement-badge";
    movement.textContent = movementLabel;
    info.append(movement);
  }
  if (sentenceIndexes.length) {
    const sentenceRow = document.createElement("div");
    sentenceRow.className = "sentence-badges";
    for (const sentenceIndex of sentenceIndexes) {
      const badge = document.createElement("span");
      badge.style.setProperty("--sentence-color", sentenceColor(sentenceIndex));
      badge.textContent = sentenceLabel(sentenceIndex);
      sentenceRow.append(badge);
    }
    info.append(sentenceRow);
  }
  button.append(thumbWrap, info);
  card.append(button);
  if (state.project?.videoUrl) {
    const playButton = document.createElement("button");
    playButton.type = "button";
    playButton.className = "play-shot-button";
    playButton.setAttribute("aria-label", `Play ${memberLabel(shot)}`);
    const playIcon = document.createElement("span");
    playIcon.className = "play-icon";
    playButton.append(playIcon);
    playButton.addEventListener("click", (event) => {
      event.stopPropagation();
      playClip(index);
    });
    card.append(playButton);
  }
  return card;
}

function startOverviewTitleEdit(index, titleText) {
  const shot = state.shots[index];
  if (!shot) return;
  const input = document.createElement("input");
  input.className = "overview-title-input";
  input.value = shotTitle(shot);
  input.setAttribute("aria-label", `Edit title for shot ${shot.shot}`);

  function commit() {
    const nextTitle = input.value.trim() || "Shot Title Pending";
    if (shot.shot_title !== nextTitle) {
      rememberUndo("shot title edit", `overview-title:${shot.shot}`);
      shot.shot_title = nextTitle;
      markManualField(shot, "shot_title");
      if (state.activeIndex === index && !els.detailView.hidden) {
        els.titleField.value = nextTitle;
      }
      markDirty("Shot title updated. Save corrections to rebuild the spreadsheet.");
    }
    renderGrid();
  }

  function cancel() {
    renderGrid();
  }

  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  });
  input.addEventListener("blur", commit);
  titleText.replaceWith(input);
  input.focus();
  input.select();
}

function openSentencePopover(sentenceIndex, clientX = window.innerWidth / 2, clientY = window.innerHeight / 2) {
  const sentence = state.outline.sentences[sentenceIndex];
  if (!sentence) return;
  state.activeSentenceIndex = sentenceIndex;
  els.sentencePopover.hidden = false;
  els.sentencePopover.style.setProperty("--sentence-color", sentenceColor(sentenceIndex));
  els.sentencePopoverLabel.textContent = sentenceLabel(sentenceIndex);
  els.sentencePopoverShots.textContent = formatShotNumbers(sentence.shotNumbers);
  els.sentenceTitleField.value = sentence.title || "";
  els.sentenceBeatField.value = sentence.beat || "";
  els.sentenceIdeaField.value = sentence.idea || "";
  positionSentencePopover(clientX, clientY);
  els.sentenceTitleField.focus();
}

function positionSentencePopover(clientX, clientY) {
  const width = Math.min(420, window.innerWidth - 28);
  els.sentencePopover.style.width = `${width}px`;
  els.sentencePopover.style.left = `${Math.max(14, Math.min(clientX + 14, window.innerWidth - width - 14))}px`;
  els.sentencePopover.style.top = `${Math.max(84, Math.min(clientY + 14, window.innerHeight - 360))}px`;
}

function closeSentencePopover(refresh = true) {
  if (!els.sentencePopover || els.sentencePopover.hidden) {
    state.activeSentenceIndex = null;
    return;
  }
  els.sentencePopover.hidden = true;
  state.activeSentenceIndex = null;
  if (refresh && state.view === "study") renderGrid();
}

function updateActiveSentenceFromPopover() {
  const sentence = activeSentence();
  if (!sentence) return;
  const nextSentence = {
    title: els.sentenceTitleField.value.trim() || "Untitled Sentence",
    beat: els.sentenceBeatField.value.trim() || "Beat",
    idea: els.sentenceIdeaField.value.trim(),
  };
  const before = JSON.stringify([sentence.title, sentence.beat, sentence.idea]);
  const after = JSON.stringify([nextSentence.title, nextSentence.beat, nextSentence.idea]);
  if (before === after) return;
  rememberUndo("sentence edit", `sentence:${sentence.id || state.activeSentenceIndex}`);
  sentence.title = els.sentenceTitleField.value.trim() || "Untitled Sentence";
  sentence.beat = els.sentenceBeatField.value.trim() || "Beat";
  sentence.idea = els.sentenceIdeaField.value.trim();
  markDirty("Sentence updated. Save corrections to keep it.");
}

function selectActiveSentenceShots() {
  const sentence = activeSentence();
  if (!sentence) return;
  state.editMode = true;
  const selectedIndexes = sentence.shotNumbers
    .map((number) => state.shots.findIndex((shot) => shot.shot === number))
    .filter((shotIndex) => shotIndex >= 0);
  state.selected = new Set(selectedIndexes);
  state.selectionAnchorIndex = selectedIndexes[0] ?? null;
  closeSentencePopover(false);
  render();
}

function removeActiveSentence() {
  if (state.activeSentenceIndex == null) return;
  rememberUndo("sentence removal");
  state.outline.sentences.splice(state.activeSentenceIndex, 1);
  markDirty("Sentence removed. Save corrections to keep it.");
  closeSentencePopover(false);
  render();
}

function selectShotRange(anchorIndex, index) {
  const start = Math.min(anchorIndex, index);
  const end = Math.max(anchorIndex, index);
  for (let shotIndex = start; shotIndex <= end; shotIndex += 1) {
    state.selected.add(shotIndex);
  }
}

function clearSelection() {
  state.selected.clear();
  state.selectionAnchorIndex = null;
}

function setSelectedAnalysisScope(excluded) {
  const selected = [...state.selected].filter((index) => state.shots[index]);
  if (!selected.length) return;
  rememberUndo(excluded ? "analysis exclusion" : "analysis inclusion");
  let changed = 0;
  for (const index of selected) {
    const shot = state.shots[index];
    if (Boolean(shot.analysis_excluded) === excluded) continue;
    shot.analysis_excluded = excluded;
    if (!excluded) shot.analysis_stale = true;
    changed += 1;
  }
  if (!changed) return;
  if (state.project?.analysisSession) {
    state.project.analysisSession.scopeChanged = true;
  }
  clearSelection();
  const menu = els.excludeSelected.closest("details");
  if (menu) menu.open = false;
  markDirty(
    excluded
      ? `Excluded ${changed} ${changed === 1 ? "shot" : "shots"} from AI analysis.`
      : `Included ${changed} ${changed === 1 ? "shot" : "shots"} for AI analysis.`
  );
  render();
}

function includeAllShots() {
  const excludedIndexes = state.shots
    .map((shot, index) => shot.analysis_excluded ? index : -1)
    .filter((index) => index >= 0);
  if (!excludedIndexes.length) return;
  state.selected = new Set(excludedIndexes);
  setSelectedAnalysisScope(false);
}

function useSelectionAsAnalysisScope() {
  const selected = new Set([...state.selected].filter((index) => state.shots[index]));
  if (!selected.size) return;
  rememberUndo("analysis scope change");
  state.shots.forEach((shot, index) => {
    const shouldExclude = !selected.has(index);
    if (shot.analysis_excluded && !shouldExclude) shot.analysis_stale = true;
    shot.analysis_excluded = shouldExclude;
  });
  if (state.project?.analysisSession) {
    state.project.analysisSession.scopeChanged = true;
  }
  const includedCount = selected.size;
  clearSelection();
  const menu = els.useSelectedAnalysis.closest("details");
  if (menu) menu.open = false;
  markDirty(`Analysis scope set to ${includedCount} selected ${includedCount === 1 ? "shot" : "shots"}.`);
  render();
}

function onShotCardClick(index, event = null) {
  if (state.editMode) {
    if (event?.shiftKey && state.selectionAnchorIndex != null) {
      selectShotRange(state.selectionAnchorIndex, index);
    } else {
      if (state.selected.has(index)) state.selected.delete(index);
      else state.selected.add(index);
      state.selectionAnchorIndex = index;
    }
    render();
    return;
  }
  openDetail(index);
}

function openDetail(index, { historyMode = "push" } = {}) {
  stopClip();
  cancelSplitMode();
  state.activeIndex = Math.max(0, Math.min(index, state.shots.length - 1));
  syncDetailFields();
  els.detailView.hidden = false;
  const shot = state.shots[state.activeIndex];
  updateNavigationHistory({
    view: "shot",
    projectId: state.project?.id || "",
    shotNumber: Number(shot?.shot) || null,
  }, historyMode);
}

function closeDetail({ historyMode = "push" } = {}) {
  cancelSplitMode();
  stopDetailClip();
  stopClip();
  saveDetailFields();
  els.detailView.hidden = true;
  state.activeIndex = null;
  renderGrid();
  updateNavigationHistory({
    view: "study",
    projectId: state.project?.id || "",
    shotNumber: null,
  }, historyMode);
}

function closeDetailIfOpen() {
  if (els.detailView.hidden) return;
  cancelSplitMode();
  stopDetailClip();
  stopClip();
  saveDetailFields();
  els.detailView.hidden = true;
  state.activeIndex = null;
}

function activeSentence() {
  if (state.activeSentenceIndex == null) return null;
  return state.outline.sentences[state.activeSentenceIndex] ?? null;
}

function syncDetailFields() {
  const shot = state.shots[state.activeIndex];
  stopDetailClip();
  els.detailVideo.hidden = true;
  els.detailImage.hidden = false;
  els.detailImage.src = shot.screenshotUrl;
  els.detailImage.alt = `${memberLabel(shot)} screenshot`;
  els.detailCounter.textContent = memberLabel(shot);
  els.detailTiming.textContent = `${formatStartTime(shot.start)} [${formatDuration(shot.duration_seconds)}]`;
  const sentenceTitle = sentenceTitleForDetail(shot.shot);
  els.detailSentenceTitle.hidden = !sentenceTitle;
  els.detailSentenceTitle.textContent = sentenceTitle || "";
  if (sentenceTitle) {
    const sentenceIndex = sentenceIndexesForShot(shot.shot)[0];
    els.detailSentenceTitle.style.setProperty("--sentence-color", sentenceColor(sentenceIndex));
  } else {
    els.detailSentenceTitle.style.removeProperty("--sentence-color");
  }
  els.titleField.value = shotTitle(shot);
  els.notesField.value = shot.notes ?? "";
  els.visualField.value = shot.visual_description ?? "";
  els.audioField.value = shot.audio_dialogue ?? "";
  els.actionField.value = shot.action_camera ?? "";
  els.narrativeField.value = shot.narrative_function ?? "";
  els.prevShot.disabled = state.activeIndex <= 0;
  els.nextShot.disabled = state.activeIndex >= state.shots.length - 1;
  els.playDetailShot.disabled = !state.project?.videoUrl;
  els.detailPlayOverlay.disabled = !state.project?.videoUrl;
  els.detailPlayOverlay.hidden = !state.project?.videoUrl;
  els.startScreencap.disabled = !state.project?.videoUrl;
  els.startSplit.disabled = !state.project?.videoUrl || shot.duration_seconds <= 0.12;
  updateSplitUi(false);
}

function activeTimelineMode() {
  if (state.splitMode) return "split";
  if (state.screencapMode) return "screencap";
  return null;
}

function activeTimelineIndex() {
  if (state.splitMode) return state.splitIndex;
  if (state.screencapMode) return state.screencapIndex;
  return null;
}

function updateSplitUi(active, mode = activeTimelineMode()) {
  els.timelineControlLabel.textContent = mode === "screencap" ? "Screencap frame" : "Cut point";
  els.startScreencap.hidden = active;
  els.startSplit.hidden = active;
  els.cancelSplit.hidden = !active;
  els.applyScreencap.hidden = !active || mode !== "screencap";
  els.applySplit.hidden = !active || mode !== "split";
  els.splitControls.hidden = !active;
}

function splitBounds(shot) {
  const start = timeToSeconds(shot.start);
  const end = timeToSeconds(shot.end);
  const inset = Math.min(0.05, Math.max(0.01, (end - start) / 4));
  return {
    start,
    end,
    min: start + inset,
    max: end - inset,
  };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

async function ensureDetailVideoReady() {
  if (els.detailVideo.readyState >= 1) return true;
  return new Promise((resolve) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      resolve(false);
    }, 3000);
    function cleanup() {
      window.clearTimeout(timeout);
      els.detailVideo.removeEventListener("loadedmetadata", onReady);
      els.detailVideo.removeEventListener("error", onError);
    }
    function onReady() {
      cleanup();
      resolve(true);
    }
    function onError() {
      cleanup();
      resolve(false);
    }
    els.detailVideo.addEventListener("loadedmetadata", onReady, { once: true });
    els.detailVideo.addEventListener("error", onError, { once: true });
    els.detailVideo.load();
  });
}

function setSplitTime(value, seekVideo = true) {
  const timelineIndex = activeTimelineIndex();
  if (timelineIndex == null) return;
  const shot = state.shots[timelineIndex];
  const bounds = splitBounds(shot);
  const nextValue = clamp(Number(value), bounds.min, bounds.max);
  els.splitSlider.value = String(nextValue);
  els.splitTime.textContent = formatStartTime(secondsToTimestamp(nextValue));
  if (seekVideo && Math.abs(els.detailVideo.currentTime - nextValue) > 0.015) {
    els.detailVideo.currentTime = nextValue;
  }
}

async function startSplitMode() {
  if (state.activeIndex == null) return;
  if (!state.project?.videoUrl) {
    setStatus("No source video found for this film.");
    return;
  }
  cancelSplitMode();
  saveDetailFields();
  stopDetailClip();
  stopClip();
  pauseFullVideo();
  const shot = state.shots[state.activeIndex];
  const bounds = splitBounds(shot);
  if (bounds.max <= bounds.min) {
    setStatus("That shot is too short to split cleanly.");
    return;
  }

  state.splitMode = true;
  state.splitIndex = state.activeIndex;
  state.screencapMode = false;
  state.screencapIndex = null;
  updateSplitUi(true, "split");
  els.detailImage.hidden = true;
  els.detailVideo.hidden = false;
  els.detailPlayOverlay.hidden = true;
  els.detailVideo.controls = true;
  if (!els.detailVideo.src.endsWith(state.project.videoUrl)) {
    els.detailVideo.src = state.project.videoUrl;
  }
  const videoReady = await ensureDetailVideoReady();
  if (!state.splitMode || state.splitIndex !== state.activeIndex) return;
  if (!videoReady) {
    setStatus("Video preview is still loading. Try Split Shot again in a moment.");
    cancelSplitMode();
    return;
  }
  els.splitSlider.min = String(bounds.min);
  els.splitSlider.max = String(bounds.max);
  els.splitSlider.step = "0.01";
  setSplitTime((bounds.start + bounds.end) / 2);
  setStatus(`Find the cut point for shot #${shot.shot}, then apply the split.`);
}

async function startScreencapMode() {
  if (state.activeIndex == null) return;
  if (!state.project?.videoUrl) {
    setStatus("No source video found for this film.");
    return;
  }
  cancelSplitMode();
  saveDetailFields();
  stopDetailClip();
  stopClip();
  const shot = state.shots[state.activeIndex];
  const bounds = splitBounds(shot);
  if (bounds.max <= bounds.min) {
    setStatus("That shot is too short to choose a new screencap.");
    return;
  }

  state.screencapMode = true;
  state.screencapIndex = state.activeIndex;
  state.splitMode = false;
  state.splitIndex = null;
  updateSplitUi(true, "screencap");
  els.detailImage.hidden = true;
  els.detailVideo.hidden = false;
  els.detailPlayOverlay.hidden = true;
  els.detailVideo.controls = true;
  if (!els.detailVideo.src.endsWith(state.project.videoUrl)) {
    els.detailVideo.src = state.project.videoUrl;
  }
  const videoReady = await ensureDetailVideoReady();
  if (!state.screencapMode || state.screencapIndex !== state.activeIndex) return;
  if (!videoReady) {
    setStatus("Video preview is still loading. Try Change Screencap again in a moment.");
    cancelSplitMode();
    return;
  }
  els.splitSlider.min = String(bounds.min);
  els.splitSlider.max = String(bounds.max);
  els.splitSlider.step = "0.01";
  setSplitTime((bounds.start + bounds.end) / 2);
  setStatus(`Choose the frame for shot #${shot.shot}, then apply the screencap.`);
}

async function playDetailClip() {
  if (state.activeIndex == null || !state.project?.videoUrl) {
    setStatus("No source video found for this project.");
    return;
  }
  cancelSplitMode();
  stopClip();
  pauseFullVideo();
  const shot = state.shots[state.activeIndex];
  const start = timeToSeconds(shot.start);
  const end = timeToSeconds(shot.end);
  state.detailClipEnd = end;
  els.detailImage.hidden = true;
  els.detailVideo.hidden = false;
  els.detailPlayOverlay.hidden = true;
  els.detailVideo.controls = true;
  els.playDetailShot.hidden = true;
  els.stopDetailShot.hidden = false;
  if (!els.detailVideo.src.endsWith(state.project.videoUrl)) {
    els.detailVideo.src = state.project.videoUrl;
  }
  const videoReady = await ensureDetailVideoReady();
  if (!videoReady || state.detailClipEnd !== end) {
    setStatus("Video preview is still loading. Try Play Shot again in a moment.");
    stopDetailClip();
    return;
  }
  els.detailVideo.currentTime = Math.max(0, start + 0.001);
  try {
    await els.detailVideo.play();
    setStatus(`Playing shot #${shot.shot}.`);
  } catch (_error) {
    setStatus("Clip is ready. Press play in the video controls.");
  }
}

function stopDetailClip() {
  state.detailClipEnd = null;
  if (!els.detailVideo) return;
  els.detailVideo.pause();
  if (!state.splitMode && !state.screencapMode) {
    els.detailVideo.hidden = true;
    els.detailImage.hidden = false;
    els.detailPlayOverlay.hidden = !state.project?.videoUrl;
  }
  if (els.playDetailShot) els.playDetailShot.hidden = false;
  if (els.stopDetailShot) els.stopDetailShot.hidden = true;
}

function cancelSplitMode() {
  if (!state.splitMode && !state.screencapMode) {
    updateSplitUi(false);
    return;
  }
  state.splitMode = false;
  state.splitIndex = null;
  state.screencapMode = false;
  state.screencapIndex = null;
  els.detailVideo.pause();
  els.detailVideo.hidden = true;
  els.detailImage.hidden = false;
  els.detailPlayOverlay.hidden = !state.project?.videoUrl;
  updateSplitUi(false);
}

async function captureSplitFrame(projectId, timestamp, label) {
  return fetchJson(`/api/projects/${encodeURIComponent(projectId)}/frame`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timestamp, label }),
  });
}

function splitShotTitle(baseTitle, suffix) {
  const cleaned = baseTitle.replace(/\s+[AB]$/, "");
  return `${cleaned} ${suffix}`;
}

function splitDetailResolution(shot) {
  return requestDetailResolution({
    title: "Split shot details",
    summary: `Shot #${shot.shot} is becoming two shots. Choose where the current title and descriptions should stay; the blank half can be regenerated cleanly.`,
    options: [
      {
        value: "first",
        label: "Keep on first half",
        description: "Best when the existing description mostly belongs before the cut. The second half will be blank for new generation.",
      },
      {
        value: "second",
        label: "Keep on second half",
        description: "Use this when the existing description mostly belongs after the cut.",
      },
      {
        value: "both",
        label: "Copy to both halves",
        description: "Useful for a split inside one continuous action, but both halves may need cleanup.",
      },
      {
        value: "blank",
        label: "Blank both halves",
        description: "Use when the old generated details are offset or unreliable.",
      },
    ],
  });
}

function requestDetailResolution({ title, summary, options }) {
  closeDetailResolution(null);
  els.detailResolutionTitle.textContent = title;
  els.detailResolutionSummary.textContent = summary;
  els.detailResolutionOptions.innerHTML = "";
  for (const option of options) {
    const button = document.createElement("button");
    button.className = "detail-resolution-option";
    button.type = "button";
    button.innerHTML = `<strong></strong><span></span>`;
    button.querySelector("strong").textContent = option.label;
    button.querySelector("span").textContent = option.description;
    button.addEventListener("click", () => closeDetailResolution(option.value), { once: true });
    els.detailResolutionOptions.append(button);
  }
  els.detailResolution.hidden = false;
  return new Promise((resolve) => {
    state.detailResolutionResolver = resolve;
  });
}

function closeDetailResolution(value = null) {
  if (!els.detailResolution) return;
  els.detailResolution.hidden = true;
  els.detailResolutionOptions.innerHTML = "";
  if (state.detailResolutionResolver) {
    const resolve = state.detailResolutionResolver;
    state.detailResolutionResolver = null;
    resolve(value);
  }
}

async function applyScreencap() {
  if (!state.screencapMode || state.screencapIndex == null || !state.project) return;
  const index = state.screencapIndex;
  const shot = state.shots[index];
  const bounds = splitBounds(shot);
  const frameTime = clamp(Number(els.splitSlider.value), bounds.min, bounds.max);
  els.applyScreencap.disabled = true;
  setStatus(`Capturing new screencap for shot #${shot.shot}...`);

  try {
    const frame = await captureSplitFrame(
      state.project.id,
      frameTime,
      `screencap_${shot.shot}_${Date.now()}`,
    );
    rememberUndo("screencap change");
    Object.assign(shot, frame);
    state.screencapMode = false;
    state.screencapIndex = null;
    els.applyScreencap.disabled = false;
    markDirty(`Changed screencap for shot #${shot.shot}. Save corrections to rebuild the spreadsheet.`);
    syncDetailFields();
    renderGrid();
  } catch (error) {
    console.error(error);
    els.applyScreencap.disabled = false;
    setStatus("Could not capture that screencap.");
  }
}

async function splitShotAt(index, cut, resolution = "blank", labelPrefix = "split", splitDetails = null) {
  const shot = state.shots[index];
  if (!shot || !state.project) throw new Error("Shot is no longer available");
  const bounds = splitBounds(shot);
  const safeCut = clamp(Number(cut), bounds.min, bounds.max);
  const firstMidpoint = (bounds.start + safeCut) / 2;
  const secondMidpoint = (safeCut + bounds.end) / 2;
  const [firstFrame, secondFrame] = await Promise.all([
    captureSplitFrame(state.project.id, firstMidpoint, `${labelPrefix}_${shot.shot}_a`),
    captureSplitFrame(state.project.id, secondMidpoint, `${labelPrefix}_${shot.shot}_b`),
  ]);
  const baseTitle = shotTitle(shot);
  const splitNote = `Split from shot #${shot.shot} at ${formatStartTime(secondsToTimestamp(safeCut))}.`;
  const firstShot = {
    ...shot,
    ...firstFrame,
    end: secondsToTimestamp(safeCut),
    duration_seconds: Number((safeCut - bounds.start).toFixed(3)),
  };
  const secondShot = {
    ...shot,
    ...secondFrame,
    start: secondsToTimestamp(safeCut),
    duration_seconds: Number((bounds.end - safeCut).toFixed(3)),
  };
  if (resolution === "ai") {
    applyAiSplitDetails(firstShot, splitDetails?.before);
  } else if (resolution === "first" || resolution === "both") {
    copyDetailFields(firstShot, shot);
    firstShot.shot_title = splitShotTitle(baseTitle, "A");
    firstShot.notes = firstShot.notes ? `${firstShot.notes}\n\n${splitNote}` : splitNote;
  } else {
    blankGeneratedDetails(firstShot, "Title Pending");
  }
  if (resolution === "ai") {
    applyAiSplitDetails(secondShot, splitDetails?.after);
  } else if (resolution === "second" || resolution === "both") {
    copyDetailFields(secondShot, shot);
    secondShot.shot_title = splitShotTitle(baseTitle, "B");
    secondShot.notes = secondShot.notes ? `${secondShot.notes}\n\n${splitNote}` : splitNote;
  } else {
    blankGeneratedDetails(secondShot, "Title Pending");
  }
  if (resolution !== "ai") {
    firstShot.analysis_stale = true;
    secondShot.analysis_stale = true;
  }
  state.shots.splice(index, 1, firstShot, secondShot);
  state.shots.forEach((item, itemIndex) => {
    item.shot = itemIndex + 1;
  });
  updateOutlineAfterSplit(shot.shot);
  return safeCut;
}

async function applySplit() {
  if (!state.splitMode || state.splitIndex == null || !state.project) return;
  const index = state.splitIndex;
  const shot = state.shots[index];
  const resolution = await splitDetailResolution(shot);
  if (!resolution) return;
  const bounds = splitBounds(shot);
  const cut = clamp(Number(els.splitSlider.value), bounds.min, bounds.max);
  els.applySplit.disabled = true;
  setStatus(`Splitting shot #${shot.shot}...`);

  try {
    rememberUndo("shot split");
    await splitShotAt(index, cut, resolution, `split_${Date.now()}`);
    clearSelection();
    state.activeIndex = index;
    state.splitMode = false;
    state.splitIndex = null;
    els.applySplit.disabled = false;
    markDirty(`Split shot #${index + 1} at ${formatStartTime(secondsToTimestamp(cut))}. Save corrections to rebuild the spreadsheet.`);
    syncDetailFields();
    renderGrid();
  } catch (error) {
    console.error(error);
    els.applySplit.disabled = false;
    setStatus("Could not split that shot.");
  }
}

async function playClip(index) {
  if (!state.project?.videoUrl) {
    setStatus("No source video found for this project.");
    return;
  }
  if (state.clipIndex === index && state.clipVideo) {
    if (state.clipVideo.paused) {
      try {
        await state.clipVideo.play();
        setStatus(`Playing shot #${state.shots[index].shot}.`);
      } catch (_error) {
        setStatus("Clip is ready. Press play in the thumbnail controls.");
      }
    } else {
      stopClip();
    }
    return;
  }
  stopClip();
  pauseFullVideo();
  const shot = state.shots[index];
  const start = timeToSeconds(shot.start);
  const end = timeToSeconds(shot.end);
  const targetTime = Math.max(0, start + 0.001);
  state.clipEnd = end;
  state.clipIndex = index;

  const card = els.shotGrid.querySelector(`[data-shot-index="${index}"]`);
  const thumbWrap = card?.querySelector(".thumb-wrap");
  const image = thumbWrap?.querySelector("img");
  if (!thumbWrap || !image) {
    setStatus("Could not open that shot clip.");
    stopClip();
    return;
  }

  const video = document.createElement("video");
  video.className = "shot-video";
  video.src = state.project.videoUrl;
  video.playsInline = true;
  video.controls = true;
  video.preload = "metadata";
  video.addEventListener("timeupdate", onClipTimeUpdate);
  video.addEventListener("ended", () => stopClip());

  image.hidden = true;
  thumbWrap.append(video);
  state.clipVideo = video;
  state.clipImage = image;

  let needsMetadataSeek = false;
  try {
    video.currentTime = targetTime;
  } catch (_error) {
    needsMetadataSeek = true;
  }

  let playRequest;
  try {
    playRequest = video.play();
  } catch (error) {
    playRequest = Promise.reject(error);
  }

  if (video.readyState < 1) {
    await new Promise((resolve) => {
      video.addEventListener("loadedmetadata", resolve, { once: true });
    });
  }
  if (state.clipVideo !== video) return;
  if (needsMetadataSeek || Math.abs(video.currentTime - targetTime) > 0.25) {
    video.currentTime = targetTime;
  }
  try {
    await playRequest;
    if (state.clipVideo !== video) return;
    setStatus(`Playing shot #${shot.shot}.`);
  } catch (_error) {
    if (state.clipVideo !== video) return;
    setStatus("Clip is ready. Press play in the thumbnail controls.");
  }
}

function stopClip() {
  state.clipEnd = null;
  state.clipIndex = null;
  if (state.clipVideo) {
    state.clipVideo.pause();
    state.clipVideo.removeEventListener("timeupdate", onClipTimeUpdate);
    state.clipVideo.remove();
  }
  if (state.clipImage) {
    state.clipImage.hidden = false;
  }
  state.clipVideo = null;
  state.clipImage = null;
  if (!els.detailVideo) return;
  els.detailVideo.pause();
}

function onClipTimeUpdate() {
  if (!state.clipVideo || state.clipEnd == null) return;
  if (state.clipVideo.currentTime >= state.clipEnd) {
    stopClip();
    setStatus("Shot clip finished.");
  }
}

function saveDetailFields() {
  if (state.activeIndex == null) return;
  const shot = state.shots[state.activeIndex];
  const before = JSON.stringify([
    shot.shot_title,
    shot.notes,
    shot.visual_description,
    shot.audio_dialogue,
    shot.action_camera,
    shot.narrative_function,
  ]);
  const nextValues = [
    els.titleField.value.trim() || "Shot Title Pending",
    els.notesField.value,
    els.visualField.value,
    els.audioField.value,
    els.actionField.value,
    els.narrativeField.value,
  ];
  const after = JSON.stringify(nextValues);
  if (before !== after) {
    rememberUndo("shot detail edit", `detail-fields:${shot.shot}`);
  }
  const fieldNames = [
    "shot_title",
    "notes",
    "visual_description",
    "audio_dialogue",
    "action_camera",
    "narrative_function",
  ];
  const previousValues = JSON.parse(before);
  nextValues.forEach((value, index) => {
    if (value !== previousValues[index]) {
      markManualField(shot, fieldNames[index]);
    }
  });
  [
    shot.shot_title,
    shot.notes,
    shot.visual_description,
    shot.audio_dialogue,
    shot.action_camera,
    shot.narrative_function,
  ] = nextValues;
  if (before !== after) markDirty("Notes updated. Save corrections to rebuild the spreadsheet.");
}

function moveDetail(delta) {
  saveDetailFields();
  openDetail(state.activeIndex + delta);
}

async function openProjectFolder() {
  if (!state.project?.id) return;
  els.openFolderButton.disabled = true;
  try {
    await fetchJson(`/api/projects/${encodeURIComponent(state.project.id)}/open-folder`, {
      method: "POST",
    });
    setStatus("Opened this study in File Explorer.");
  } catch (error) {
    console.error(error);
    setStatus(readErrorMessage(error, "Could not open this study folder."));
  } finally {
    els.openFolderButton.disabled = false;
  }
}

async function restoreNavigation(target) {
  try {
    if (!target.projectId || target.view === "home") {
      showHome({ historyMode: "none" });
      return;
    }
    if (state.project?.id !== target.projectId) {
      await loadProject(target.projectId, {
        historyMode: "none",
        shotNumber: target.view === "shot" ? target.shotNumber : null,
      });
      return;
    }
    if (target.view === "shot" && target.shotNumber) {
      const index = state.shots.findIndex((shot) => Number(shot.shot) === Number(target.shotNumber));
      if (index >= 0) {
        openDetail(index, { historyMode: "none" });
        return;
      }
    }
    if (!els.detailView.hidden) {
      closeDetail({ historyMode: "none" });
    }
  } catch (error) {
    console.error(error);
    setStatus(readErrorMessage(error, "Could not restore that page."));
  }
}

function markDirty(message) {
  state.dirty = true;
  els.saveButton.disabled = false;
  setStatus(message);
}

async function combineRange(indices) {
  const selected = [...indices].sort((a, b) => a - b);
  if (!selected.length) return;
  const firstIndex = selected[0];
  const lastIndex = selected[selected.length - 1];
  const range = state.shots.slice(firstIndex, lastIndex + 1);
  const resolution = await askCombineDetailResolution(range);
  if (!resolution) return;
  rememberUndo("shot combine");
  const members = range.flatMap((shot) => Array.isArray(shot.members) ? shot.members : [shot.originalShot ?? shot.shot]);
  const first = range[0];
  const last = range[range.length - 1];
  const combined = {
    ...first,
    members,
    end: last.end,
    duration_seconds: Number((timeToSeconds(last.end) - timeToSeconds(first.start)).toFixed(3)),
    analysis_excluded: range.every((shot) => Boolean(shot.analysis_excluded)),
  };
  if (resolution.mode === "source" && resolution.source) {
    copyDetailFields(combined, resolution.source);
  } else if (resolution.mode === "merge") {
    combined.shot_title = makeCombinedTitle(range);
    combined.visual_description = makeCombinedVisual(range);
    combined.notes = makeCombinedNotes(range);
    combined.audio_dialogue = makeCombinedAudio(range);
    combined.action_camera = makeCombinedAction(range);
    combined.camera_movement_type = "";
    combined.camera_movement_intensity = "";
    combined.camera_movement_confidence = "";
    combined.camera_movement_evidence = "";
    combined.narrative_function = makeCombinedNarrative(range);
    combined.manual_fields = [];
    combined.analysis_stale = true;
  } else {
    blankGeneratedDetails(combined, "Title Pending");
  }
  combined.analysis_stale = true;
  state.shots.splice(firstIndex, range.length, combined);
  state.shots.forEach((shot, index) => {
    shot.shot = index + 1;
  });
  updateOutlineAfterCombine(first.shot, last.shot);
  clearSelection();
  markDirty(`Combined ${range.length} shots into shot #${firstIndex + 1}.`);
  render();
}

function linkSelectedSentence() {
  const selected = [...state.selected].sort((a, b) => a - b);
  const adjacent = selected.length >= 2 && selected.every((value, index) => index === 0 || value === selected[index - 1] + 1);
  if (!adjacent) {
    setStatus("Select adjacent shots before linking a sentence.");
    return;
  }
  rememberUndo("sentence link");
  const shotNumbers = selected.map((index) => state.shots[index].shot);
  const sentence = {
    id: makeSentenceId(),
    beat: nextBeatName(),
    title: `Shots ${formatShotNumbers(shotNumbers)}`,
    idea: "",
    shotNumbers,
  };
  state.outline.sentences.push(sentence);
  clearSelection();
  markDirty(`Linked ${formatShotNumbers(shotNumbers)} as ${sentenceLabel(state.outline.sentences.length - 1)}.`);
  render();
  window.requestAnimationFrame(() => {
    const group = els.shotGrid.querySelector(`[data-sentence-index="${state.outline.sentences.length - 1}"]`);
    const rect = group?.getBoundingClientRect();
    openSentencePopover(
      state.outline.sentences.length - 1,
      rect ? rect.left + 18 : window.innerWidth / 2,
      rect ? rect.top + 18 : window.innerHeight / 2,
    );
  });
}

function contiguousShotRuns(numbers) {
  const ordered = normalizeShotNumbers(numbers);
  const runs = [];
  for (const number of ordered) {
    if (!runs.length || number !== runs[runs.length - 1][runs[runs.length - 1].length - 1] + 1) {
      runs.push([number]);
    } else {
      runs[runs.length - 1].push(number);
    }
  }
  return runs;
}

function removeSelectedFromSentences() {
  const selectedNumbers = new Set(
    [...state.selected]
      .map((index) => state.shots[index]?.shot)
      .filter((number) => Number.isInteger(number))
  );
  if (!selectedNumbers.size) return;
  const affected = state.outline.sentences.filter((sentence) =>
    sentence.shotNumbers.some((number) => selectedNumbers.has(number))
  );
  if (!affected.length) {
    setStatus("The selected shots are not part of a sentence.");
    return;
  }

  rememberUndo("remove shots from sentence");
  const nextSentences = [];
  for (const sentence of state.outline.sentences) {
    const remaining = sentence.shotNumbers.filter((number) => !selectedNumbers.has(number));
    const runs = contiguousShotRuns(remaining);
    runs.forEach((run, runIndex) => {
      nextSentences.push({
        ...sentence,
        id: runIndex ? `${sentence.id}-continued-${runIndex + 1}-${Date.now()}` : sentence.id,
        title: runIndex ? `${sentence.title || "Sentence"} (continued)` : sentence.title,
        shotNumbers: run,
      });
    });
  }
  nextSentences.sort((a, b) => a.shotNumbers[0] - b.shotNumbers[0]);
  state.outline = normalizeOutline({ sentences: nextSentences });
  const removedNumbers = [...selectedNumbers].sort((a, b) => a - b);
  clearSelection();
  closeSentencePopover(false);
  markDirty(
    `Removed ${formatShotNumbers(removedNumbers)} from ${affected.length === 1 ? "its sentence" : `${affected.length} sentences`}.`
  );
  render();
}

function nextBeatName() {
  const lastBeat = state.outline.sentences.at(-1)?.beat;
  return lastBeat || "Beat 1";
}

function updateOutlineAfterSplit(originalShotNumber) {
  state.outline.sentences.forEach((sentence) => {
    const nextNumbers = [];
    for (const number of sentence.shotNumbers) {
      if (number < originalShotNumber) nextNumbers.push(number);
      else if (number === originalShotNumber) nextNumbers.push(number, number + 1);
      else nextNumbers.push(number + 1);
    }
    sentence.shotNumbers = normalizeShotNumbers(nextNumbers);
  });
}

function updateOutlineAfterCombine(firstShotNumber, lastShotNumber) {
  const removedCount = lastShotNumber - firstShotNumber;
  state.outline.sentences.forEach((sentence) => {
    const nextNumbers = [];
    for (const number of sentence.shotNumbers) {
      if (number < firstShotNumber) nextNumbers.push(number);
      else if (number <= lastShotNumber) nextNumbers.push(firstShotNumber);
      else nextNumbers.push(number - removedCount);
    }
    sentence.shotNumbers = normalizeShotNumbers(nextNumbers);
  });
}

function makeCombinedNotes(range) {
  const existing = range.map((shot) => shot.notes).filter(Boolean).join("\n\n");
  const source = range.map((shot) => `#${shot.shot}`).join(", ");
  return existing ? `Combined from ${source}.\n\n${existing}` : `Combined from ${source}.`;
}

function makeCombinedTitle(range) {
  const first = range[0];
  const last = range[range.length - 1];
  if (range.length === 1) return shotTitle(first);
  return `${shotTitle(first)} / ${shotTitle(last)}`;
}

function makeCombinedVisual(range) {
  return range.map((shot) => shot.visual_description).filter(Boolean).join("\n\n");
}

function makeCombinedAction(range) {
  const actions = range.map((shot) => shot.action_camera).filter(Boolean);
  return actions.join("\n\n");
}

function makeCombinedAudio(range) {
  const audio = range.map((shot) => shot.audio_dialogue).filter(Boolean);
  return audio.join("\n\n");
}

function makeCombinedNarrative(range) {
  const beats = range.map((shot) => shot.narrative_function).filter(Boolean);
  return beats.join("\n\n");
}

async function askCombineDetailResolution(range) {
  const choice = await requestDetailResolution({
    title: "Combine shot details",
    summary: `${range.length} shots are becoming one shot. Choose whether to keep an existing description, merge the selected text temporarily, or blank the combined shot for new generation.`,
    options: [
      {
        value: "blank",
        label: "Blank for new generation",
        description: "Best when details are offset or the combined shot should be analyzed fresh.",
      },
      {
        value: "merge",
        label: "Merge selected text",
        description: "Keeps a temporary combined title, notes, dialogue, action, and narrative text.",
      },
      {
        value: "source:first",
        label: `Keep first: #${range[0].shot}`,
        description: shotTitle(range[0]),
      },
      {
        value: "source:last",
        label: `Keep last: #${range[range.length - 1].shot}`,
        description: shotTitle(range[range.length - 1]),
      },
      ...range.slice(1, -1).map((shot, index) => ({
        value: `source:middle:${index + 1}`,
        label: `Keep #${shot.shot}`,
        description: shotTitle(shot),
      })),
    ],
  });
  if (!choice) return null;
  if (choice === "blank") return { mode: "blank" };
  if (choice === "merge") return { mode: "merge" };
  if (choice === "source:first") return { mode: "source", source: range[0] };
  if (choice === "source:last") return { mode: "source", source: range[range.length - 1] };
  if (choice.startsWith("source:middle:")) {
    const offset = Number(choice.split(":").at(-1));
    const source = range.slice(1, -1)[offset - 1];
    if (source) return { mode: "source", source };
  }
  return null;
}

function timeToSeconds(value) {
  const [hours, minutes, seconds] = value.split(":");
  return Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds);
}

async function saveCorrections({ preserveUndo = false } = {}) {
  saveDetailFields();
  els.saveButton.disabled = true;
  setStatus("Saving corrections and rebuilding corrected spreadsheet...");
  const result = await fetchJson(`/api/projects/${encodeURIComponent(state.project.id)}/corrections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shots: state.shots, outline: state.outline, userContext: els.filmContextField.value }),
  });
  state.outline = normalizeOutline(result.outline);
  state.project.analysisSession = result.analysisSession || state.project.analysisSession;
  state.project.cutReview = result.cutReview || state.project.cutReview;
  state.dirty = false;
  if (!preserveUndo) clearUndoHistory();
  setStatus(`Saved ${result.shotCount} corrected shots. Corrected spreadsheet rebuilt.`);
  await refreshProjectList();
  return result;
}

async function applyAiShotSuggestions(suggestions, { automatic = false } = {}) {
  const selected = [...suggestions]
    .filter(Boolean)
    .sort((a, b) => Number(a.time_seconds) - Number(b.time_seconds));
  if (!selected.length) {
    if (!automatic) setStatus("Select at least one suggested cut.");
    return 0;
  }
  rememberUndo(automatic ? "automatic AI cuts" : "AI shot refinement");
  setStatus(`Applying ${selected.length} AI ${selected.length === 1 ? "cut" : "cuts"}...`);
  let appliedCount = 0;
  try {
    for (let suggestionIndex = 0; suggestionIndex < selected.length; suggestionIndex += 1) {
      const cut = Number(selected[suggestionIndex].time_seconds);
      const shotIndex = state.shots.findIndex((shot) => {
        const start = timeToSeconds(shot.start);
        const end = timeToSeconds(shot.end);
        return start + 0.25 < cut && cut < end - 0.25;
      });
      if (shotIndex < 0) continue;
      await splitShotAt(
        shotIndex,
        cut,
        "ai",
        `ai_${Date.now()}_${suggestionIndex + 1}`,
        {
          before: selected[suggestionIndex].before_details,
          after: selected[suggestionIndex].after_details,
        },
      );
      appliedCount += 1;
    }
    clearSelection();
    state.activeIndex = null;
    markDirty("AI cuts applied. Saving the updated timeline and captions...");
    render();
    await saveCorrections({ preserveUndo: true });
    setStatus(
      `${appliedCount} AI ${appliedCount === 1 ? "cut was" : "cuts were"} applied and saved automatically. Undo is available in Edit mode.`
    );
    return appliedCount;
  } catch (error) {
    console.error(error);
    markDirty("Some AI cut refinements could not be completed. Undo is available.");
    render();
    setStatus(readErrorMessage(error, "Could not apply every selected cut."));
    return appliedCount;
  }
}

async function generateShotDetails({ reprocess = false } = {}) {
  if (!state.project || !state.shots.length) return;
  const analysisProjectId = state.project.id;
  saveDetailFields();
  await saveProjectContext();
  if (!QWEN_VIDEO_MODELS.has(els.modelField.value)) {
    els.modelField.value = DEFAULT_QWEN_VIDEO_MODEL;
  }
  saveLlmSettings();
  els.generateDetails.disabled = true;
  els.reprocessVideo.disabled = true;
  els.saveButton.disabled = true;
  const hasFullAnalysis = Boolean(state.project.analysisSession?.hasFullAnalysis);
  const changedCount = Math.max(
    Number(state.project.analysisSession?.changedShotCount || 0),
    state.shots.filter((shot) => shot.analysis_stale && !shot.analysis_excluded).length,
  );
  const needsNarrativeContinuity = Boolean(state.project.analysisSession?.needsNarrativeContinuity);
  const needsAiCutUpgrade = Boolean(state.project.analysisSession?.needsAiCutUpgrade);
  const needsSentenceOutline = Boolean(state.project.analysisSession?.needsSentenceOutline);
  const scopeChanged = Boolean(state.project.analysisSession?.scopeChanged);
  let progressMessage = "";
  if (needsNarrativeContinuity && hasFullAnalysis && !reprocess) {
    progressMessage = "Preparing a subtitle-aware narrative pass from the complete existing shot catalogue.";
    setStatus("Repairing narrative functions from the saved English subtitles without resending the video...");
  } else if (reprocess || !hasFullAnalysis || needsAiCutUpgrade || scopeChanged) {
    progressMessage = "Preparing the included film scope, soundtrack, and latest edited shot timeline.";
    setStatus(
      scopeChanged
        ? "Rebuilding film memory from the included part of the film..."
        : needsAiCutUpgrade
        ? "Upgrading the analysis, rechecking cuts with the video model, and rebuilding film memory..."
        : "Watching the included part of the film, listening to its soundtrack, and building film memory..."
    );
  } else if (needsSentenceOutline && !changedCount) {
    progressMessage = "Organizing the complete shot catalogue into filmic sentences and beats.";
    setStatus("Building filmic sentences from the saved analysis without resending video...");
  } else if (!changedCount) {
    progressMessage = "Preparing your updated film notes with saved film memory.";
    setStatus("Reconsidering your updated film notes from saved film memory without resending video...");
  } else {
    progressMessage = `Preparing ${changedCount} changed shot${changedCount === 1 ? "" : "s"} and neighboring context.`;
    setStatus(`Updating ${changedCount} changed shot${changedCount === 1 ? "" : "s"} from saved film memory...`);
  }
  renderAnalysisJob({
    status: "running",
    phase: "preparing",
    message: progressMessage,
    progress: 1,
    elapsedSeconds: 0,
    provider: "qwen",
    model: els.modelField.value,
  });
  startAnalysisClock(0);
  state.analysisPollTimer = window.setTimeout(() => pollAnalysisStatus(analysisProjectId), 500);
  try {
    const result = await fetchJson(`/api/projects/${encodeURIComponent(analysisProjectId)}/generate-details`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: els.modelField.value,
        userContext: els.filmContextField.value,
        shots: state.shots,
        outline: state.outline,
        reprocess: reprocess || needsAiCutUpgrade,
      }),
    });
    if (!state.project || state.project.id !== analysisProjectId) {
      await refreshProjectList();
      return;
    }
    state.shots = result.shots;
    state.outline = normalizeOutline(result.outline);
    state.project.analysisSession = result.analysisSession || state.project.analysisSession;
    state.project.cutReview = result.cutReview || state.project.cutReview;
    state.analyzedContext = els.filmContextField.value;
    state.dirty = false;
    stopAnalysisPolling();
    const displayedUsage = result.upToDate
      ? result.analysisSession?.lastUsage
      : (result.usage || result.analysisSession?.lastUsage);
    renderAnalysisJob(result.analysisJob ? { ...result.analysisJob, usage: displayedUsage } : {
      status: "completed",
      phase: "complete",
      message: result.upToDate
        ? "Analysis was already current; no API request was sent."
        : "Analysis complete. Shot details and spreadsheet are ready.",
      progress: 100,
      elapsedSeconds: state.analysisJob?.elapsedSeconds || 0,
      provider: result.provider,
      model: result.model,
      usage: displayedUsage,
    });
    renderAnalysisUsage(displayedUsage);
    renderAnalysisHistory(state.project.analysisSession?.analysisHistory);
    els.saveButton.disabled = true;
    renderGrid();
    if (state.activeIndex != null) {
      state.activeIndex = Math.min(state.activeIndex, state.shots.length - 1);
      syncDetailFields();
    }
    if (result.suggestionCount) {
      setStatus(
        `The model found ${result.suggestionCount} missing ${result.suggestionCount === 1 ? "cut" : "cuts"}. Applying them automatically...`
      );
      await applyAiShotSuggestions(result.suggestions, { automatic: true });
      return;
    }
    if (result.appliedCutCount) {
      setStatus(
        `Analysis complete. ${result.appliedCutCount} missing ${
          result.appliedCutCount === 1 ? "cut was" : "cuts were"
        } applied automatically before the final narrative pass and spreadsheet save.`
      );
    } else if (result.upToDate) {
      setStatus("Analysis is already current. No video was sent again.");
    } else {
      const scope = result.analysisMode === "incremental"
        ? `${result.analyzedShotCount} changed ${result.analyzedShotCount === 1 ? "shot" : "shots"}`
        : result.analysisMode === "memory"
          ? "the saved film memory without resending video"
          : result.analysisMode === "continuity"
            ? "narrative continuity across the complete existing shot catalogue"
          : "the complete film";
      setStatus(`Analyzed ${scope} with ${result.model || result.provider || "video analysis"}. Corrected spreadsheet rebuilt.`);
    }
    await refreshProjectList();
  } catch (error) {
    console.error(error);
    if (!state.project || state.project.id !== analysisProjectId) return;
    stopAnalysisPolling();
    renderAnalysisJob({
      status: "failed",
      phase: "failed",
      message: readErrorMessage(error, "Could not generate shot details."),
      progress: 0,
      elapsedSeconds: state.analysisJob?.elapsedSeconds || 0,
      usage: state.analysisJob?.usage,
    });
    els.saveButton.disabled = !state.dirty;
    setStatus(readErrorMessage(error, "Could not generate shot details."));
    try {
      const refreshed = await fetchJson(`/api/projects/${encodeURIComponent(analysisProjectId)}`);
      if (state.project?.id === analysisProjectId) {
        state.project.analysisSession = refreshed.analysisSession || state.project.analysisSession;
        renderAnalysisHistory(state.project.analysisSession?.analysisHistory);
      }
    } catch (refreshError) {
      console.error(refreshError);
    }
  } finally {
    els.generateDetails.disabled = false;
    renderAnalysisControls();
  }
}

async function reprocessFullVideo() {
  if (!state.project) return;
  const confirmed = window.confirm(
    "Reprocess the complete video? This starts fresh film memory and uses substantially more model input than updating changed shots.",
  );
  if (!confirmed) return;
  const menu = els.reprocessVideo.closest("details");
  if (menu) menu.open = false;
  await generateShotDetails({ reprocess: true });
}

function readErrorMessage(error, fallback) {
  const text = String(error?.message ?? error ?? "");
  const messageMatch = text.match(/<p>Message:\s*([^<]+)<\/p>/i);
  if (messageMatch) return messageMatch[1];
  return text || fallback;
}

function showToast(message) {
  window.clearTimeout(state.toastTimer);
  els.toast.textContent = message;
  els.toast.hidden = false;
  requestAnimationFrame(() => els.toast.classList.add("is-visible"));
  state.toastTimer = window.setTimeout(() => {
    els.toast.classList.remove("is-visible");
    window.setTimeout(() => {
      els.toast.hidden = true;
    }, 180);
  }, 2600);
}

async function copyTextToClipboard(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const fallback = document.createElement("textarea");
  fallback.value = value;
  fallback.style.position = "fixed";
  fallback.style.opacity = "0";
  document.body.append(fallback);
  fallback.select();
  const copied = document.execCommand("copy");
  fallback.remove();
  if (!copied) throw new Error("Clipboard access was unavailable");
}

function downloadTextFile(filename, content) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportForAi() {
  if (!state.project) return;
  els.exportForAi.disabled = true;
  setStatus("Preparing the AI study handoff...");
  try {
    saveDetailFields();
    if (state.dirty) await saveCorrections();
    else await saveProjectContext();
    const result = await fetchJson(
      `/api/projects/${encodeURIComponent(state.project.id)}/export-ai`,
      { method: "POST" },
    );
    downloadTextFile(result.filename || "Film Study.md", result.markdown);
    await copyTextToClipboard(result.markdown);
    showToast("Copied to clipboard successfully.");
    setStatus("Markdown study exported and copied to your clipboard.");
  } catch (error) {
    console.error(error);
    setStatus(readErrorMessage(error, "Could not export this study."));
    showToast("Export could not be completed.");
  } finally {
    els.exportForAi.disabled = false;
  }
}

function renderFilmChat(conversation = state.project?.conversation) {
  const messages = Array.isArray(conversation?.messages) ? conversation.messages : [];
  els.filmChatMessages.replaceChildren();
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "film-chat-empty";
    empty.textContent = "Qwen has the saved film memory, your notes, sentences, and included shot catalogue. Ask what the film is doing, challenge an interpretation, or look for a missed pattern.";
    els.filmChatMessages.append(empty);
  } else {
    for (const message of messages) {
      const row = document.createElement("article");
      row.className = `film-chat-message is-${message.role === "user" ? "user" : "assistant"}`;
      const label = document.createElement("strong");
      label.textContent = message.role === "user" ? "You" : "Qwen";
      const content = document.createElement("div");
      content.textContent = String(message.content || "");
      row.append(label, content);
      els.filmChatMessages.append(row);
    }
  }
  els.filmChatMessages.scrollTop = els.filmChatMessages.scrollHeight;
  const model = conversation?.model || state.project?.analysisSession?.model || "Qwen";
  els.filmChatModel.textContent = `Continuing with ${model} from saved film memory`;
}

async function openFilmChat() {
  if (!state.project) return;
  if (state.dirty) await saveCorrections();
  els.filmChat.hidden = false;
  document.body.classList.add("has-dialog");
  els.filmChatStatus.textContent = "Loading saved conversation...";
  try {
    const conversation = await fetchJson(
      `/api/projects/${encodeURIComponent(state.project.id)}/conversation`,
    );
    state.project.conversation = conversation;
    renderFilmChat(conversation);
    els.filmChatStatus.textContent = "";
    els.filmChatQuestion.focus();
  } catch (error) {
    console.error(error);
    els.filmChatStatus.textContent = readErrorMessage(error, "Could not load the conversation.");
  }
}

function closeFilmChat() {
  els.filmChat.hidden = true;
  document.body.classList.remove("has-dialog");
}

async function sendFilmChat(event) {
  event.preventDefault();
  if (!state.project || state.chatSending) return;
  const question = els.filmChatQuestion.value.trim();
  if (!question) return;
  state.chatSending = true;
  els.sendFilmChat.disabled = true;
  els.filmChatQuestion.disabled = true;
  els.filmChatStatus.textContent = "Qwen is thinking with the saved film context...";
  const optimistic = {
    ...(state.project.conversation || { messages: [] }),
    messages: [
      ...((state.project.conversation?.messages) || []),
      { role: "user", content: question },
    ],
  };
  renderFilmChat(optimistic);
  els.filmChatQuestion.value = "";
  try {
    const result = await fetchJson(
      `/api/projects/${encodeURIComponent(state.project.id)}/ask`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      },
    );
    state.project.conversation = result.conversation;
    renderFilmChat(result.conversation);
    const tokenCount = Number(result.usage?.totalTokens || 0);
    els.filmChatStatus.textContent = tokenCount
      ? `${tokenCount.toLocaleString()} tokens used`
      : `Answered with ${result.model || "Qwen"}`;
  } catch (error) {
    console.error(error);
    renderFilmChat(state.project.conversation);
    els.filmChatQuestion.value = question;
    els.filmChatStatus.textContent = readErrorMessage(error, "Qwen could not answer.");
  } finally {
    state.chatSending = false;
    els.sendFilmChat.disabled = false;
    els.filmChatQuestion.disabled = false;
    els.filmChatQuestion.focus();
  }
}

async function clearFilmChat() {
  if (!state.project) return;
  if (!window.confirm("Start a new conversation for this film? The saved film analysis will remain available.")) return;
  try {
    const result = await fetchJson(
      `/api/projects/${encodeURIComponent(state.project.id)}/conversation/clear`,
      { method: "POST" },
    );
    state.project.conversation = result.conversation;
    renderFilmChat(result.conversation);
    els.filmChatStatus.textContent = "New conversation started. Film memory is still loaded.";
  } catch (error) {
    console.error(error);
    els.filmChatStatus.textContent = readErrorMessage(error, "Could not start a new conversation.");
  }
}

function compactImportReason(value) {
  const lines = String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const preferred = [...lines].reverse().find((line) => /^ERROR:/i.test(line)) || lines.at(-1) || "Import failed.";
  return preferred.replace(/^ERROR:\s*/i, "").slice(0, 220);
}

function setUploadStatus(message) {
  els.uploadStatus.textContent = message;
}

function extractUrls(text) {
  const urls = [];
  const seen = new Set();
  for (const match of String(text || "").matchAll(/https?:\/\/[^\s<>)\]"']+/g)) {
    const url = match[0].replace(/[.,;:]+$/g, "");
    try {
      const key = sourceUrlKey(url);
      if (!seen.has(key)) {
        seen.add(key);
        urls.push(url);
      }
    } catch {
      // Ignore malformed fragments from copied rich text.
    }
  }
  return urls;
}

function sourceUrlKey(url) {
  const parsed = new URL(url);
  let host = parsed.hostname.toLowerCase().replace(/^www\./, "");
  const path = parsed.pathname.replace(/\/$/, "");
  if (["youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"].includes(host)) {
    let videoId = "";
    if (host === "youtu.be") {
      videoId = path.replace(/^\//, "").split("/", 1)[0];
    } else if (path === "/watch") {
      videoId = parsed.searchParams.get("v") || "";
    } else {
      videoId = path.match(/^\/(?:shorts|embed|live)\/([^/?#]+)/)?.[1] || "";
    }
    return videoId ? `youtube.com/watch?v=${videoId}` : `youtube.com${path}`;
  }

  const ignored = new Set(["fbclid", "gclid", "igshid", "lang", "ref", "si", "source", "spm"]);
  const stableParams = [...parsed.searchParams.entries()]
    .filter(([key]) => !ignored.has(key.toLowerCase()) && !key.toLowerCase().startsWith("utm_"))
    .sort(([leftKey, leftValue], [rightKey, rightValue]) => (
      leftKey.localeCompare(rightKey) || leftValue.localeCompare(rightValue)
    ));
  const query = new URLSearchParams(stableParams).toString();
  return `${host}${path}${query ? `?${query}` : ""}`;
}

function isChannelUrl(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    const path = parsed.pathname.replace(/\/$/, "");
    if (host.includes("tiktok.com")) {
      return /^\/@[^/]+$/.test(path);
    }
    if (host.includes("youtube.com")) {
      return /^\/(@|channel\/|c\/|user\/)/.test(path) && !path.startsWith("/watch") && !path.startsWith("/shorts/");
    }
  } catch {
    return false;
  }
  return false;
}

async function uploadVideo(file) {
  if (!file || state.uploading) return;
  state.uploading = true;
  els.uploadDrop.classList.add("is-uploading");
  setUploadStatus(`Breaking down ${file.name}...`);
  const form = new FormData();
  form.append("video", file);
  try {
    const result = await fetchJson("/api/projects/upload", {
      method: "POST",
      body: form,
    });
    await refreshProjectList();
    setUploadStatus("Breakdown complete.");
    await loadProject(result.project.id);
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not break down that video."));
  } finally {
    state.uploading = false;
    els.uploadDrop.classList.remove("is-uploading", "is-dragging");
    els.uploadInput.value = "";
  }
}

async function importLinks() {
  const text = els.channelUrlField.value.trim();
  const urls = extractUrls(text);
  if ((!text && !urls.length) || state.importingChannel) return;
  state.importingChannel = true;
  els.importChannelButton.disabled = true;
  els.channelUrlField.disabled = true;
  els.channelLimitField.disabled = true;
  const channelUrls = urls.filter(isChannelUrl);
  const videoUrls = urls.filter((url) => !isChannelUrl(url));
  const useChannelImport = channelUrls.length === 1 && videoUrls.length === 0;
  setUploadStatus(useChannelImport ? "Scanning channel videos by view count..." : `Importing ${videoUrls.length || urls.length || 1} selected link${(videoUrls.length || urls.length) === 1 ? "" : "s"}...`);
  try {
    const result = await fetchJson(useChannelImport ? "/api/channels/import" : "/api/urls/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(useChannelImport ? {
        url: channelUrls[0],
        limit: Number(els.channelLimitField.value) || 5,
        scanLimit: 100,
      } : {
        text,
        urls: videoUrls.length ? videoUrls : urls,
      }),
    });
    await refreshProjectList();
    const importedCount = result.imported?.length || 0;
    const skippedCount = result.skipped?.length || 0;
    const skippedSummaries = (result.skipped || []).map((item) => (
      `${item.title || item.url || "Video"}: ${compactImportReason(item.reason)}`
    ));
    const skippedText = skippedCount ? ` ${skippedCount} skipped: ${skippedSummaries.join(" | ")}` : "";
    const target = result.groupPath?.join(" / ") || result.channelTitle || "the library";
    if (!useChannelImport && importedCount) {
      els.channelUrlField.value = (result.skipped || []).map((item) => item.url).filter(Boolean).join("\n");
    }
    const readyText = importedCount
      ? " Initial cuts, screenshots, captions, and spreadsheets are ready; review the cuts before generating AI shot details."
      : "";
    setUploadStatus(useChannelImport
      ? `Imported ${importedCount} most popular videos into ${target}.${readyText}${skippedText}`
      : `Imported ${importedCount} selected video${importedCount === 1 ? "" : "s"} into ${target}.${readyText}${skippedText}`);
  } catch (error) {
    console.error(error);
    setUploadStatus(readErrorMessage(error, "Could not import those links."));
  } finally {
    state.importingChannel = false;
    els.importChannelButton.disabled = false;
    els.channelUrlField.disabled = false;
    els.channelLimitField.disabled = false;
  }
}

function filesFromEvent(event) {
  return event.dataTransfer?.files ?? event.target.files ?? [];
}

els.projectSelect.addEventListener("change", (event) => loadProject(event.target.value));
els.homeButton.addEventListener("click", showHome);
els.openFolderButton.addEventListener("click", openProjectFolder);
els.createFolderButton.addEventListener("click", () => createFolder());
els.editToggle.addEventListener("click", () => {
  state.editMode = !state.editMode;
  clearSelection();
  render();
});
els.uploadDrop.addEventListener("click", () => els.uploadInput.click());
els.uploadDrop.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.uploadInput.click();
  }
});
els.uploadInput.addEventListener("change", (event) => {
  const [file] = filesFromEvent(event);
  uploadVideo(file);
});
els.importChannelButton.addEventListener("click", importLinks);
els.channelUrlField.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    importLinks();
  }
});
for (const eventName of ["dragenter", "dragover"]) {
  els.uploadDrop.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (!state.uploading) els.uploadDrop.classList.add("is-dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  els.uploadDrop.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.uploadDrop.classList.remove("is-dragging");
  });
}
els.uploadDrop.addEventListener("drop", (event) => {
  const [file] = filesFromEvent(event);
  if (file) {
    uploadVideo(file);
    return;
  }
  const text = event.dataTransfer?.getData("text/plain") || event.dataTransfer?.getData("text/uri-list") || "";
  if (text.trim()) {
    els.channelUrlField.value = text.trim();
    importLinks();
  }
});
els.combineSelected.addEventListener("click", () => combineRange(state.selected));
els.fullVideoToggle.addEventListener("click", toggleFullVideo);
els.fullVideo.addEventListener("play", () => {
  stopClip();
  stopDetailClip();
});
els.combineWithNext.addEventListener("click", () => {
  const [index] = [...state.selected];
  combineRange(new Set([index, index + 1]));
});
els.linkSentence.addEventListener("click", linkSelectedSentence);
els.removeFromSentence.addEventListener("click", removeSelectedFromSentences);
els.useSelectedAnalysis.addEventListener("click", useSelectionAsAnalysisScope);
els.excludeSelected.addEventListener("click", () => setSelectedAnalysisScope(true));
els.includeSelected.addEventListener("click", () => setSelectedAnalysisScope(false));
els.includeAllShots.addEventListener("click", includeAllShots);
els.clearSelection.addEventListener("click", () => {
  clearSelection();
  render();
});
els.undoEdit.addEventListener("click", undoLastEdit);
els.saveButton.addEventListener("click", saveCorrections);
els.generateDetails.addEventListener("click", () => generateShotDetails());
els.reprocessVideo.addEventListener("click", reprocessFullVideo);
els.askThisFilm.addEventListener("click", () => {
  openFilmChat().catch((error) => {
    console.error(error);
    setStatus(readErrorMessage(error, "Could not open the film conversation."));
  });
});
els.exportForAi.addEventListener("click", exportForAi);
els.filmChatForm.addEventListener("submit", sendFilmChat);
els.closeFilmChat.addEventListener("click", closeFilmChat);
els.clearFilmChat.addEventListener("click", clearFilmChat);
els.filmChat.querySelector(".film-chat-backdrop").addEventListener("click", closeFilmChat);
els.modelField.addEventListener("change", saveLlmSettings);
els.filmContextField.addEventListener("input", scheduleContextSave);
els.cancelDetailResolution.addEventListener("click", () => closeDetailResolution(null));
els.detailResolution.addEventListener("click", (event) => {
  if (event.target === els.detailResolution) closeDetailResolution(null);
});
els.closeSentencePopover.addEventListener("click", () => closeSentencePopover());
els.sentencePopover.addEventListener("click", (event) => event.stopPropagation());
els.sentenceTitleField.addEventListener("input", updateActiveSentenceFromPopover);
els.sentenceBeatField.addEventListener("input", updateActiveSentenceFromPopover);
els.sentenceIdeaField.addEventListener("input", updateActiveSentenceFromPopover);
els.selectSentenceShots.addEventListener("click", selectActiveSentenceShots);
els.removeSentence.addEventListener("click", removeActiveSentence);
els.closeDetail.addEventListener("click", closeDetail);
els.prevShot.addEventListener("click", () => moveDetail(-1));
els.nextShot.addEventListener("click", () => moveDetail(1));
els.playDetailShot.addEventListener("click", playDetailClip);
els.detailPlayOverlay.addEventListener("click", playDetailClip);
els.stopDetailShot.addEventListener("click", () => {
  stopDetailClip();
  setStatus("Shot playback stopped.");
});
els.startScreencap.addEventListener("click", startScreencapMode);
els.startSplit.addEventListener("click", startSplitMode);
els.cancelSplit.addEventListener("click", () => {
  cancelSplitMode();
  setStatus("Timeline selection cancelled.");
});
els.applyScreencap.addEventListener("click", applyScreencap);
els.applySplit.addEventListener("click", applySplit);
els.splitSlider.addEventListener("input", (event) => setSplitTime(event.target.value));
els.nudgeBack.addEventListener("click", () => setSplitTime(Number(els.splitSlider.value) - 0.05));
els.nudgeForward.addEventListener("click", () => setSplitTime(Number(els.splitSlider.value) + 0.05));
els.detailVideo.addEventListener("timeupdate", () => {
  const timelineIndex = activeTimelineIndex();
  if (timelineIndex != null) {
    const shot = state.shots[timelineIndex];
    const bounds = splitBounds(shot);
    if (els.detailVideo.currentTime >= bounds.max) {
      els.detailVideo.pause();
      setSplitTime(bounds.max);
    } else if (els.detailVideo.currentTime <= bounds.min) {
      setSplitTime(bounds.min, false);
    } else {
      setSplitTime(els.detailVideo.currentTime, false);
    }
    return;
  }
  if (state.detailClipEnd == null) return;
  if (els.detailVideo.currentTime >= state.detailClipEnd) {
    stopDetailClip();
    setStatus("Shot clip finished.");
  }
});

els.detailVideo.addEventListener("ended", () => {
  if (state.detailClipEnd != null) {
    stopDetailClip();
    setStatus("Shot clip finished.");
  }
});

for (const field of [els.titleField, els.notesField, els.visualField, els.audioField, els.actionField, els.narrativeField]) {
  field.addEventListener("input", () => {
    saveDetailFields();
    renderGrid();
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "BrowserBack") {
    event.preventDefault();
    window.history.back();
    return;
  }
  if (event.key === "BrowserForward") {
    event.preventDefault();
    window.history.forward();
    return;
  }
  if (event.key === "Escape" && !els.detailResolution.hidden) {
    closeDetailResolution(null);
    return;
  }
  if (event.key === "Escape" && !els.filmChat.hidden) {
    closeFilmChat();
    return;
  }
  if (event.key === "Escape" && !els.sentencePopover.hidden) {
    closeSentencePopover();
    return;
  }
  if (els.detailView.hidden) return;
  if (event.key === "Escape") closeDetail();
  if (event.key === "ArrowLeft" && !els.prevShot.disabled) moveDetail(-1);
  if (event.key === "ArrowRight" && !els.nextShot.disabled) moveDetail(1);
});

document.addEventListener("pointermove", updateCoverCropDrag);
document.addEventListener("pointerup", endCoverCropDrag);
document.addEventListener("pointercancel", endCoverCropDrag);

window.addEventListener("popstate", (event) => {
  restoreNavigation(navigationTarget(event.state));
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".film-card-actions")) {
    for (const menu of els.filmGrid.querySelectorAll(".film-card-actions[open]")) {
      menu.open = false;
    }
  }
  if (!event.target.closest(".folder-actions-menu")) {
    for (const menu of els.filmGrid.querySelectorAll(".folder-actions-menu[open]")) {
      menu.open = false;
    }
  }
  if (!els.sentencePopover.hidden) {
    if (event.target.closest(".sentence-popover, .sentence-shot-group")) return;
    closeSentencePopover();
  }
});

loadLlmSettings();
loadProjects().catch((error) => {
  console.error(error);
  setStatus("Could not load film study outputs.");
});
