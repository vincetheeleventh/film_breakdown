const state = {
  projects: [],
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
  hiddenFolders: new Set(),
  fullVideoOpen: false,
  dirty: false,
};

const DEFAULT_QWEN_VIDEO_MODEL = "qwen3.7-plus";
const QWEN_VIDEO_MODELS = new Set([
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
  filmGrid: document.querySelector("#filmGrid"),
  statusText: document.querySelector("#statusText"),
  studySourcePanel: document.querySelector("#studySourcePanel"),
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
  detailView: document.querySelector("#detailView"),
  closeDetail: document.querySelector("#closeDetail"),
  prevShot: document.querySelector("#prevShot"),
  nextShot: document.querySelector("#nextShot"),
  detailImage: document.querySelector("#detailImage"),
  detailVideo: document.querySelector("#detailVideo"),
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
};

function formatDuration(seconds) {
  return `${Number(seconds).toFixed(2)}s`;
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

  els.studySourcePanel.hidden = !sourceUrl && !statItems.length;
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
  const legacyModels = new Set(["qwen-vl-max-latest", "qwen-vl-plus-latest"]);
  els.modelField.value =
    QWEN_VIDEO_MODELS.has(savedModel) && !legacyModels.has(savedModel)
      ? savedModel
      : DEFAULT_QWEN_VIDEO_MODEL;
}

function saveLlmSettings() {
  localStorage.setItem("filmStudyModel", els.modelField.value);
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

async function loadProjects() {
  const data = await fetchJson("/api/projects");
  state.projects = data.projects;
  populateProjectSelect();
  showHome();
}

async function refreshProjectList() {
  const currentId = state.project?.id;
  const data = await fetchJson("/api/projects");
  state.projects = data.projects;
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

async function loadProject(projectId) {
  if (!projectId) {
    showHome();
    return;
  }
  const data = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}`);
  state.project = data;
  state.shots = data.shots;
  state.outline = normalizeOutline(data.outline);
  const loadedContext = data.userContext || "";
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
  els.saveButton.disabled = true;
  els.projectSelect.value = data.id;
  els.projectMeta.textContent = `${data.name} - ${data.shots.length} shots`;
  renderStudySource(data);
  renderFullVideo(data);
  setStatus("Overview ready.");
  render();
}

function showHome() {
  stopClip();
  pauseFullVideo();
  closeDetailIfOpen();
  closeSentencePopover(false);
  state.view = "home";
  state.project = null;
  state.shots = [];
  state.outline = { sentences: [] };
  setProjectContext("", "", false);
  clearSelection();
  clearUndoHistory();
  state.editMode = false;
  renderStudySource(null);
  renderFullVideo(null);
  els.projectSelect.value = "";
  els.projectMeta.textContent = `${state.projects.length} films`;
  render();
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
    renderSelection();
    renderGrid();
  } else {
    renderHome();
  }
}

function renderHome() {
  const fragment = document.createDocumentFragment();
  if (!state.projects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-library";
    empty.textContent = "No film breakdowns yet.";
    fragment.append(empty);
  }
  const tree = buildProjectTree(state.projects);
  for (const node of tree.children.values()) {
    fragment.append(renderProjectGroup(node));
  }
  if (tree.projects.length) {
    const section = document.createElement("section");
    section.className = "film-folder";
    const heading = document.createElement("h2");
    heading.textContent = "Ungrouped";
    const grid = document.createElement("div");
    grid.className = "film-grid-row";
    for (const project of tree.projects) {
      grid.append(createFilmCard(project));
    }
    section.append(heading, grid);
    fragment.append(section);
  }
  els.filmGrid.replaceChildren(fragment);
}

function buildProjectTree(projects) {
  const root = { name: "", path: [], children: new Map(), projects: [] };
  for (const project of projects) {
    const path = Array.isArray(project.groupPath) ? project.groupPath.filter(Boolean) : [];
    let node = root;
    for (const part of path) {
      if (!node.children.has(part)) {
        node.children.set(part, { name: part, path: [...node.path, part], children: new Map(), projects: [] });
      }
      node = node.children.get(part);
    }
    node.projects.push(project);
  }
  return root;
}

function renderProjectGroup(node) {
  const section = document.createElement("section");
  section.className = "film-folder";
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

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "folder-action-button delete-folder-button";
  deleteButton.textContent = "Delete folder";
  deleteButton.addEventListener("click", () => deleteFolder(node));
  actions.append(toggleButton, deleteButton);
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
  }
  return section;
}

function folderPathKey(path) {
  return Array.isArray(path) ? path.join("\u001f") : "";
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
  const title = document.createElement("div");
  title.className = "film-title";
  title.textContent = project.name;
  const meta = document.createElement("div");
  meta.className = "film-meta";
  const metaParts = [`${project.shotCount} shots${project.hasCorrections ? " - corrected" : ""}`];
  if (project.channelRank) {
    const views = Number(project.viewCount || 0).toLocaleString();
    metaParts.push(`#${project.channelRank} on ${project.channelTitle || "channel"}${views !== "0" ? ` - ${views} views` : ""}`);
  }
  meta.textContent = metaParts.join(" | ");
  copy.append(title, meta);
  openButton.append(poster, copy);

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

  card.append(openButton, actions);
  return card;
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
  if (!projects.length) return;
  const folderName = node.path.join(" / ");
  const confirmed = window.confirm(
    `Delete folder "${folderName}" and ${projects.length} ${projects.length === 1 ? "study" : "studies"} inside it? This cannot be undone.`
  );
  if (!confirmed) return;
  setUploadStatus(`Deleting ${folderName}...`);
  try {
    for (const project of projects) {
      await fetchJson(`/api/projects/${encodeURIComponent(project.id)}/delete`, {
        method: "POST",
      });
    }
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
  els.combineWithNext.disabled = selected.length !== 1 || selected[0] >= state.shots.length - 1;
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

function openDetail(index) {
  stopClip();
  cancelSplitMode();
  state.activeIndex = Math.max(0, Math.min(index, state.shots.length - 1));
  syncDetailFields();
  els.detailView.hidden = false;
}

function closeDetail() {
  cancelSplitMode();
  stopDetailClip();
  stopClip();
  saveDetailFields();
  els.detailView.hidden = true;
  state.activeIndex = null;
  renderGrid();
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

async function applySplit() {
  if (!state.splitMode || state.splitIndex == null || !state.project) return;
  const index = state.splitIndex;
  const shot = state.shots[index];
  const bounds = splitBounds(shot);
  const cut = clamp(Number(els.splitSlider.value), bounds.min, bounds.max);
  const firstMidpoint = (bounds.start + cut) / 2;
  const secondMidpoint = (cut + bounds.end) / 2;
  els.applySplit.disabled = true;
  setStatus(`Splitting shot #${shot.shot}...`);

  try {
    const [firstFrame, secondFrame] = await Promise.all([
      captureSplitFrame(state.project.id, firstMidpoint, `split_${shot.shot}_a`),
      captureSplitFrame(state.project.id, secondMidpoint, `split_${shot.shot}_b`),
    ]);
    rememberUndo("shot split");
    const baseTitle = shotTitle(shot);
    const splitNote = `Split from shot #${shot.shot} at ${formatStartTime(secondsToTimestamp(cut))}.`;
    const firstShot = {
      ...shot,
      ...firstFrame,
      shot_title: splitShotTitle(baseTitle, "A"),
      end: secondsToTimestamp(cut),
      duration_seconds: Number((cut - bounds.start).toFixed(3)),
      notes: shot.notes ? `${shot.notes}\n\n${splitNote}` : splitNote,
      analysis_stale: true,
    };
    const secondShot = {
      ...shot,
      ...secondFrame,
      shot_title: splitShotTitle(baseTitle, "B"),
      start: secondsToTimestamp(cut),
      duration_seconds: Number((bounds.end - cut).toFixed(3)),
      notes: shot.notes ? `${shot.notes}\n\n${splitNote}` : splitNote,
      analysis_stale: true,
    };
    state.shots.splice(index, 1, firstShot, secondShot);
    state.shots.forEach((item, itemIndex) => {
      item.shot = itemIndex + 1;
    });
    updateOutlineAfterSplit(shot.shot);
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

function markDirty(message) {
  state.dirty = true;
  els.saveButton.disabled = false;
  setStatus(message);
}

function combineRange(indices) {
  const selected = [...indices].sort((a, b) => a - b);
  if (!selected.length) return;
  rememberUndo("shot combine");
  const firstIndex = selected[0];
  const lastIndex = selected[selected.length - 1];
  const range = state.shots.slice(firstIndex, lastIndex + 1);
  const members = range.flatMap((shot) => Array.isArray(shot.members) ? shot.members : [shot.originalShot ?? shot.shot]);
  const first = range[0];
  const last = range[range.length - 1];
  const combined = {
    ...first,
    members,
    shot_title: makeCombinedTitle(range),
    end: last.end,
    duration_seconds: Number((timeToSeconds(last.end) - timeToSeconds(first.start)).toFixed(3)),
    notes: makeCombinedNotes(range),
    audio_dialogue: makeCombinedAudio(range),
    action_camera: makeCombinedAction(range),
    narrative_function: makeCombinedNarrative(range),
    analysis_stale: true,
  };
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

function timeToSeconds(value) {
  const [hours, minutes, seconds] = value.split(":");
  return Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds);
}

async function saveCorrections() {
  saveDetailFields();
  els.saveButton.disabled = true;
  setStatus("Saving corrections and rebuilding corrected spreadsheet...");
  const result = await fetchJson(`/api/projects/${encodeURIComponent(state.project.id)}/corrections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shots: state.shots, outline: state.outline, userContext: els.filmContextField.value }),
  });
  state.outline = normalizeOutline(result.outline);
  state.dirty = false;
  clearUndoHistory();
  setStatus(`Saved ${result.shotCount} corrected shots. Corrected spreadsheet rebuilt.`);
  await refreshProjectList();
}

async function generateShotDetails() {
  if (!state.project || !state.shots.length) return;
  saveDetailFields();
  await saveProjectContext();
  if (!QWEN_VIDEO_MODELS.has(els.modelField.value)) {
    els.modelField.value = DEFAULT_QWEN_VIDEO_MODEL;
  }
  saveLlmSettings();
  els.generateDetails.disabled = true;
  els.saveButton.disabled = true;
  setStatus("Generating shot details from the native video...");
  try {
    const result = await fetchJson(`/api/projects/${encodeURIComponent(state.project.id)}/generate-details`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: els.modelField.value,
        userContext: els.filmContextField.value,
        shots: state.shots,
        outline: state.outline,
      }),
    });
    state.shots = result.shots;
    state.outline = normalizeOutline(result.outline);
    state.dirty = false;
    els.saveButton.disabled = true;
    renderGrid();
    if (state.activeIndex != null) {
      state.activeIndex = Math.min(state.activeIndex, state.shots.length - 1);
      syncDetailFields();
    }
    setStatus(`Generated details for ${result.shotCount} shots with ${result.provider || "video analysis"}. Corrected spreadsheet rebuilt.`);
    await refreshProjectList();
  } catch (error) {
    console.error(error);
    els.saveButton.disabled = !state.dirty;
    setStatus(readErrorMessage(error, "Could not generate shot details."));
  } finally {
    els.generateDetails.disabled = false;
  }
}

function readErrorMessage(error, fallback) {
  const text = String(error?.message ?? error ?? "");
  const messageMatch = text.match(/<p>Message:\s*([^<]+)<\/p>/i);
  if (messageMatch) return messageMatch[1];
  return text || fallback;
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
      const parsed = new URL(url);
      const key = `${parsed.hostname.toLowerCase()}${parsed.pathname.replace(/\/$/, "")}`;
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
    setUploadStatus("Could not break down that video.");
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
    const skippedText = skippedCount ? ` ${skippedCount} skipped.` : "";
    const target = result.groupPath?.join(" / ") || result.channelTitle || "the library";
    setUploadStatus(useChannelImport
      ? `Imported ${importedCount} most popular videos into ${target}.${skippedText}`
      : `Imported ${importedCount} selected video${importedCount === 1 ? "" : "s"} into ${target}.${skippedText}`);
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
els.clearSelection.addEventListener("click", () => {
  clearSelection();
  render();
});
els.undoEdit.addEventListener("click", undoLastEdit);
els.saveButton.addEventListener("click", saveCorrections);
els.generateDetails.addEventListener("click", generateShotDetails);
els.modelField.addEventListener("change", saveLlmSettings);
els.filmContextField.addEventListener("input", scheduleContextSave);
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

document.addEventListener("click", (event) => {
  if (!event.target.closest(".film-card-actions")) {
    for (const menu of els.filmGrid.querySelectorAll(".film-card-actions[open]")) {
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
