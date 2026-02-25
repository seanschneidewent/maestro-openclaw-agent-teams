import fs from "node:fs";
import os from "node:os";
import path from "node:path";

type AnyRecord = Record<string, unknown>;

const TOOL_PREFIX = "maestro_";
const SCHEDULE_FILE = "maestro_schedule.json";
const PROJECT_NOTES_FILE = "project_notes.json";
const SCHEDULE_TYPES = new Set(["activity", "milestone", "constraint", "inspection", "delivery", "task"]);
const SCHEDULE_STATUSES = new Set(["pending", "in_progress", "blocked", "done", "cancelled"]);
const NOTE_STATUSES = new Set(["open", "archived"]);
const NOTE_COLORS = new Set(["slate", "blue", "green", "amber", "red", "purple"]);

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return value !== 0;
  }
  if (typeof value === "string") {
    const lowered = value.trim().toLowerCase();
    if (["1", "true", "yes", "y", "on"].includes(lowered)) return true;
    if (["0", "false", "no", "n", "off"].includes(lowered)) return false;
  }
  return fallback;
}

function nowIso(): string {
  return new Date().toISOString();
}

function readJson(filePath: string, fallback: unknown = {}): unknown {
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeJson(filePath: string, payload: unknown): void {
  const parent = path.dirname(filePath);
  fs.mkdirSync(parent, { recursive: true });
  const tempPath = `${filePath}.tmp`;
  fs.writeFileSync(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
  fs.renameSync(tempPath, filePath);
}

function slugifyUnderscore(value: string, fallback = "item"): string {
  const clean = value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return clean || fallback;
}

function slugifyDash(value: string, fallback = "project"): string {
  const clean = value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return clean || fallback;
}

function normalizePageToken(value: string): string {
  return value.toLowerCase().replace(/[.\-\s]+/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
}

function truncateText(value: unknown, limit = 2500): string {
  const text = asString(value);
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function listSlice(value: unknown, limit = 12): unknown[] {
  return Array.isArray(value) ? value.slice(0, Math.max(0, limit)) : [];
}

function resolveAwarenessUrls(workspaceDir: string): {
  recommended_url: string;
  tailnet_url: string;
  localhost_url: string;
} {
  const fallbackLocal = "http://localhost:3000/workspace";
  const awarenessPath = path.join(workspaceDir, "AWARENESS.md");
  if (!fs.existsSync(awarenessPath)) {
    return {
      recommended_url: fallbackLocal,
      tailnet_url: "",
      localhost_url: fallbackLocal,
    };
  }

  const content = fs.readFileSync(awarenessPath, "utf-8");
  const recommended = (content.match(/Recommended Workspace URL:\s*`([^`]+)`/i) || [])[1] || "";
  const tailnet = (content.match(/Tailnet Workspace URL:\s*`([^`]+)`/i) || [])[1] || "";
  const localhost = (content.match(/Local Workspace URL:\s*`([^`]+)`/i) || [])[1] || fallbackLocal;
  return {
    recommended_url: recommended || tailnet || localhost || fallbackLocal,
    tailnet_url: tailnet || "",
    localhost_url: localhost || fallbackLocal,
  };
}

function resolveStoreRoot(pluginConfig: AnyRecord, workspaceDir: string): string {
  const configStore = asString(pluginConfig.storeRoot);
  const envStore = asString(process.env.MAESTRO_STORE);
  const raw = configStore || envStore || "knowledge_store";
  if (path.isAbsolute(raw)) {
    return raw;
  }
  return path.resolve(workspaceDir, raw);
}

type ProjectRef = {
  dir: string;
  slug: string;
  name: string;
  storeRoot: string;
};

function readInstallState(): AnyRecord {
  const installPath = path.join(os.homedir(), ".maestro-solo", "install.json");
  return asRecord(readJson(installPath, {}));
}

function discoverProjects(storeRoot: string): ProjectRef[] {
  if (!fs.existsSync(storeRoot)) {
    return [];
  }

  const fromDir = (projectDir: string): ProjectRef => {
    const meta = asRecord(readJson(path.join(projectDir, "project.json"), {}));
    const rawName = asString(meta.name) || path.basename(projectDir);
    const rawSlug = asString(meta.slug) || slugifyDash(rawName, slugifyDash(path.basename(projectDir)));
    return {
      dir: projectDir,
      slug: rawSlug,
      name: rawName,
      storeRoot,
    };
  };

  const directProjectMeta = path.join(storeRoot, "project.json");
  if (fs.existsSync(directProjectMeta)) {
    return [fromDir(storeRoot)];
  }

  const projects: ProjectRef[] = [];
  for (const entry of fs.readdirSync(storeRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) {
      continue;
    }
    if (entry.name.startsWith(".")) {
      continue;
    }
    const candidate = path.join(storeRoot, entry.name);
    if (fs.existsSync(path.join(candidate, "project.json"))) {
      projects.push(fromDir(candidate));
    }
  }
  projects.sort((a, b) => a.name.localeCompare(b.name));
  return projects;
}

function resolveProject(pluginConfig: AnyRecord, workspaceDir: string): ProjectRef {
  const storeRoot = resolveStoreRoot(pluginConfig, workspaceDir);
  const projects = discoverProjects(storeRoot);
  if (projects.length === 0) {
    throw new Error(`No ingested project found at ${storeRoot}. Run maestro-solo ingest <path-to-pdfs>.`);
  }

  const installState = readInstallState();
  const requestedSlug = asString(process.env.MAESTRO_ACTIVE_PROJECT_SLUG) || asString(installState.active_project_slug);
  if (requestedSlug) {
    const selected = projects.find((item) => item.slug.toLowerCase() === requestedSlug.toLowerCase());
    if (selected) {
      return selected;
    }
  }

  const requestedName = asString(installState.active_project_name);
  if (requestedName) {
    const selected = projects.find((item) => item.name.toLowerCase() === requestedName.toLowerCase());
    if (selected) {
      return selected;
    }
  }

  return projects[0];
}

function loadProjectIndex(project: ProjectRef): AnyRecord {
  return asRecord(readJson(path.join(project.dir, "index.json"), {}));
}

function listProjectPages(project: ProjectRef): string[] {
  const pagesDir = path.join(project.dir, "pages");
  if (!fs.existsSync(pagesDir)) {
    return [];
  }
  const names = fs
    .readdirSync(pagesDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => fs.existsSync(path.join(pagesDir, name, "pass1.json")));
  names.sort((a, b) => a.localeCompare(b));
  return names;
}

function resolvePageName(project: ProjectRef, requestedPageName: string): string {
  const token = asString(requestedPageName);
  if (!token) {
    throw new Error("page_name is required.");
  }
  const pages = listProjectPages(project);
  if (pages.includes(token)) {
    return token;
  }

  const normalized = normalizePageToken(token);

  const prefixMatches = pages.filter((name) => {
    const nameToken = normalizePageToken(name);
    return nameToken.startsWith(normalized);
  });
  if (prefixMatches.length >= 1) {
    return prefixMatches[0];
  }

  const includesMatches = pages.filter((name) => normalizePageToken(name).includes(normalized));
  if (includesMatches.length >= 1) {
    return includesMatches[0];
  }

  throw new Error(`Page '${token}' not found.`);
}

function loadPass1(project: ProjectRef, pageName: string): AnyRecord {
  return asRecord(readJson(path.join(project.dir, "pages", pageName, "pass1.json"), {}));
}

function loadPass2(project: ProjectRef, pageName: string, regionId: string): AnyRecord {
  return asRecord(readJson(path.join(project.dir, "pages", pageName, "pointers", regionId, "pass2.json"), {}));
}

function workspacesDir(project: ProjectRef): string {
  const value = path.join(project.dir, "workspaces");
  fs.mkdirSync(value, { recursive: true });
  return value;
}

function workspacePath(project: ProjectRef, workspaceSlug: string): string {
  return path.join(workspacesDir(project), workspaceSlug, "workspace.json");
}

function loadWorkspace(project: ProjectRef, workspaceSlug: string): AnyRecord | null {
  const wsPath = workspacePath(project, workspaceSlug);
  if (!fs.existsSync(wsPath)) {
    return null;
  }
  const payload = asRecord(readJson(wsPath, {}));
  return payload;
}

function saveWorkspace(project: ProjectRef, workspaceSlug: string, payload: AnyRecord): void {
  const wsPath = workspacePath(project, workspaceSlug);
  const dir = path.dirname(wsPath);
  fs.mkdirSync(dir, { recursive: true });
  writeJson(wsPath, payload);
}

function ensureWorkspace(project: ProjectRef, workspaceSlug: string, title: string, description: string): AnyRecord {
  const existing = loadWorkspace(project, workspaceSlug);
  if (existing) {
    return existing;
  }

  const fresh: AnyRecord = {
    slug: workspaceSlug,
    title: title || workspaceSlug,
    description: description || "",
    created_at: nowIso(),
    pages: [],
    notes: [],
    generated_images: [],
  };
  saveWorkspace(project, workspaceSlug, fresh);
  return fresh;
}

function ensureWorkspacePage(workspace: AnyRecord, pageName: string): AnyRecord {
  const pages = Array.isArray(workspace.pages) ? workspace.pages : [];
  workspace.pages = pages;
  const existing = pages.find((entry) => asString(asRecord(entry).page_name) === pageName);
  if (existing && typeof existing === "object" && existing !== null) {
    return asRecord(existing);
  }
  const created: AnyRecord = {
    page_name: pageName,
    description: "",
    selected_pointers: [],
    highlights: [],
    custom_highlights: [],
  };
  pages.push(created);
  return created;
}

function projectNotesFilePath(project: ProjectRef): string {
  const notesDir = path.join(project.dir, "notes");
  fs.mkdirSync(notesDir, { recursive: true });
  return path.join(notesDir, PROJECT_NOTES_FILE);
}

function normalizeNoteStatus(value: unknown): string {
  const normalized = asString(value).toLowerCase().replace(/[\s-]+/g, "_");
  return NOTE_STATUSES.has(normalized) ? normalized : "open";
}

function normalizeNoteColor(value: unknown): string {
  const normalized = asString(value).toLowerCase().replace(/\s+/g, "_");
  return NOTE_COLORS.has(normalized) ? normalized : "slate";
}

function normalizeCategoryName(value: unknown, fallback: string): string {
  const text = asString(value);
  if (text) return text;
  return fallback.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function normalizeSourcePages(raw: AnyRecord, fallbackWorkspaceSlug = ""): AnyRecord[] {
  const rows: AnyRecord[] = [];
  const sourcePagesRaw = raw.source_pages;
  if (Array.isArray(sourcePagesRaw)) {
    for (const item of sourcePagesRaw) {
      if (typeof item === "string") {
        const pageName = asString(item);
        if (pageName) rows.push({ page_name: pageName });
        continue;
      }
      const entry = asRecord(item);
      const pageName = asString(entry.page_name || entry.source_page || entry.name);
      if (!pageName) continue;
      const workspaceSlug = slugifyUnderscore(asString(entry.workspace_slug || entry.ws_slug || entry.workspace || fallbackWorkspaceSlug), "");
      rows.push(workspaceSlug ? { page_name: pageName, workspace_slug: workspaceSlug } : { page_name: pageName });
    }
  }

  const legacySourcePage = asString(raw.source_page);
  if (legacySourcePage) {
    const workspaceSlug = slugifyUnderscore(asString(raw.workspace_slug || fallbackWorkspaceSlug), "");
    rows.push(workspaceSlug ? { page_name: legacySourcePage, workspace_slug: workspaceSlug } : { page_name: legacySourcePage });
  }

  const seen = new Set<string>();
  const deduped: AnyRecord[] = [];
  for (const row of rows) {
    const pageName = asString(row.page_name);
    if (!pageName) continue;
    const workspaceSlug = slugifyUnderscore(asString(row.workspace_slug), "");
    const key = `${workspaceSlug}::${pageName}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(workspaceSlug ? { page_name: pageName, workspace_slug: workspaceSlug } : { page_name: pageName });
  }
  return deduped;
}

function normalizeProjectNotes(payloadRaw: AnyRecord): AnyRecord {
  const rawCategories = Array.isArray(payloadRaw.categories) ? payloadRaw.categories : [];
  const rawNotes = Array.isArray(payloadRaw.notes) ? payloadRaw.notes : [];

  const categories: AnyRecord[] = [];
  const categoriesById = new Map<string, AnyRecord>();
  for (let idx = 0; idx < rawCategories.length; idx += 1) {
    const entry = asRecord(rawCategories[idx]);
    const categoryId = slugifyUnderscore(asString(entry.id || entry.name), "category");
    if (categoriesById.has(categoryId)) continue;
    const row: AnyRecord = {
      id: categoryId,
      name: normalizeCategoryName(entry.name, categoryId),
      color: normalizeNoteColor(entry.color),
      order: Number.isFinite(asNumber(entry.order, NaN)) ? Math.trunc(asNumber(entry.order, 0)) : idx * 10,
      created_at: asString(entry.created_at),
      updated_at: asString(entry.updated_at),
    };
    categoriesById.set(categoryId, row);
    categories.push(row);
  }

  if (!categoriesById.has("general")) {
    const general: AnyRecord = { id: "general", name: "General", color: "slate", order: 0, created_at: "", updated_at: "" };
    categories.unshift(general);
    categoriesById.set("general", general);
  }

  const notes: AnyRecord[] = [];
  const seenNoteIds = new Set<string>();
  for (let idx = 0; idx < rawNotes.length; idx += 1) {
    const entry = asRecord(rawNotes[idx]);
    const text = asString(entry.text);
    if (!text) continue;
    let noteId = slugifyUnderscore(asString(entry.id || entry.note_id), "");
    if (!noteId) noteId = `note_${idx + 1}`;
    if (seenNoteIds.has(noteId)) noteId = `${noteId}_${idx + 1}`;
    seenNoteIds.add(noteId);

    let categoryId = slugifyUnderscore(asString(entry.category_id || entry.category), "general");
    if (!categoriesById.has(categoryId)) {
      const row: AnyRecord = {
        id: categoryId,
        name: normalizeCategoryName(entry.category_name, categoryId),
        color: normalizeNoteColor(entry.category_color || entry.color),
        order: categories.length * 10,
        created_at: "",
        updated_at: "",
      };
      categories.push(row);
      categoriesById.set(categoryId, row);
    }
    if (!categoryId) categoryId = "general";

    const sourcePages = normalizeSourcePages(entry, asString(entry.workspace_slug));
    notes.push({
      id: noteId,
      text,
      category_id: categoryId,
      source_pages: sourcePages,
      source_page: sourcePages.length ? asString(sourcePages[0].page_name) : "",
      pinned: asBoolean(entry.pinned, false),
      status: normalizeNoteStatus(entry.status),
      created_at: asString(entry.created_at),
      updated_at: asString(entry.updated_at),
    });
  }

  categories.sort((a, b) => {
    const orderA = Math.trunc(asNumber(asRecord(a).order, 0));
    const orderB = Math.trunc(asNumber(asRecord(b).order, 0));
    if (orderA !== orderB) return orderA - orderB;
    return asString(asRecord(a).name).localeCompare(asString(asRecord(b).name));
  });

  return {
    version: Math.max(1, Math.trunc(asNumber(payloadRaw.version, 1))),
    updated_at: asString(payloadRaw.updated_at),
    categories,
    notes,
  };
}

function loadProjectNotes(project: ProjectRef): AnyRecord {
  return normalizeProjectNotes(asRecord(readJson(projectNotesFilePath(project), {})));
}

function saveProjectNotes(project: ProjectRef, payloadRaw: AnyRecord): AnyRecord {
  const payload = normalizeProjectNotes(payloadRaw);
  const output: AnyRecord = {
    version: payload.version,
    updated_at: nowIso(),
    categories: Array.isArray(payload.categories) ? payload.categories : [],
    notes: Array.isArray(payload.notes) ? payload.notes : [],
  };
  writeJson(projectNotesFilePath(project), output);
  return output;
}

function scheduleFilePath(project: ProjectRef): string {
  const scheduleDir = path.join(project.dir, "schedule");
  fs.mkdirSync(scheduleDir, { recursive: true });
  return path.join(scheduleDir, SCHEDULE_FILE);
}

function normalizeScheduleType(value: unknown): string {
  const normalized = asString(value).toLowerCase().replace(/[\s-]+/g, "_");
  return SCHEDULE_TYPES.has(normalized) ? normalized : "activity";
}

function normalizeScheduleStatus(value: unknown): string {
  const normalized = asString(value).toLowerCase().replace(/[\s-]+/g, "_");
  return SCHEDULE_STATUSES.has(normalized) ? normalized : "pending";
}

function normalizeScheduleItem(item: AnyRecord): AnyRecord | null {
  const id = slugifyUnderscore(asString(item.id));
  if (!id) {
    return null;
  }
  const notes = asString(item.notes) || asString(item.description);
  return {
    id,
    title: asString(item.title),
    type: normalizeScheduleType(item.type),
    status: normalizeScheduleStatus(item.status),
    due_date: asString(item.due_date || item.date),
    owner: asString(item.owner),
    activity_id: asString(item.activity_id),
    impact: asString(item.impact),
    notes,
    description: notes,
    created_at: asString(item.created_at),
    updated_at: asString(item.updated_at),
    closed_at: asString(item.closed_at),
    close_reason: asString(item.close_reason),
  };
}

function loadSchedule(project: ProjectRef): AnyRecord {
  const payload = asRecord(readJson(scheduleFilePath(project), {}));
  const rawItems = Array.isArray(payload.items) ? payload.items : [];
  const items = rawItems
    .map((entry) => normalizeScheduleItem(asRecord(entry)))
    .filter((entry): entry is AnyRecord => Boolean(entry));
  return {
    version: Number.isFinite(asNumber(payload.version, 1)) ? asNumber(payload.version, 1) : 1,
    updated_at: asString(payload.updated_at),
    items,
  };
}

function saveSchedule(project: ProjectRef, payload: AnyRecord): void {
  const safeItems = Array.isArray(payload.items)
    ? payload.items.map((entry) => normalizeScheduleItem(asRecord(entry))).filter((entry) => Boolean(entry))
    : [];
  writeJson(scheduleFilePath(project), {
    version: Math.max(1, Math.trunc(asNumber(payload.version, 1))),
    updated_at: nowIso(),
    items: safeItems,
  });
}

function upsertScheduleItem(project: ProjectRef, payload: AnyRecord): { created: boolean; item: AnyRecord } {
  const schedule = loadSchedule(project);
  const items = Array.isArray(schedule.items) ? [...schedule.items] : [];
  const title = asString(payload.title);
  const requestedId = asString(payload.item_id || payload.id);
  const itemId = slugifyUnderscore(requestedId || title, "");
  if (!itemId) {
    throw new Error("item_id or title is required.");
  }

  const now = nowIso();
  const existingIndex = items.findIndex((entry) => asString(asRecord(entry).id) === itemId);
  const previous = existingIndex >= 0 ? asRecord(items[existingIndex]) : null;
  const nextItem: AnyRecord = {
    id: itemId,
    title: title || asString(previous?.title),
    type: normalizeScheduleType(payload.type || previous?.type),
    status: normalizeScheduleStatus(payload.status || previous?.status),
    due_date: asString(payload.due_date || payload.date || previous?.due_date),
    owner: asString(payload.owner || previous?.owner),
    activity_id: asString(payload.activity_id || previous?.activity_id),
    impact: asString(payload.impact || previous?.impact),
    notes: asString(payload.notes || payload.description || previous?.notes || previous?.description),
    description: asString(payload.notes || payload.description || previous?.notes || previous?.description),
    created_at: asString(previous?.created_at) || now,
    updated_at: now,
    closed_at: asString(previous?.closed_at),
    close_reason: asString(previous?.close_reason),
  };

  if (!nextItem.title) {
    throw new Error("title is required when creating a new item.");
  }

  if (nextItem.status === "done" || nextItem.status === "cancelled") {
    nextItem.closed_at = nextItem.closed_at || now;
  } else {
    nextItem.closed_at = "";
    nextItem.close_reason = "";
  }

  if (existingIndex >= 0) {
    items[existingIndex] = nextItem;
  } else {
    items.push(nextItem);
  }

  schedule.items = items;
  saveSchedule(project, schedule);
  return {
    created: existingIndex < 0,
    item: nextItem,
  };
}

function parseDate(value: string): Date | null {
  if (!value) {
    return null;
  }
  const raw = value.length >= 10 ? value.slice(0, 10) : value;
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) {
    return null;
  }
  return dt;
}

function monthBounds(month: string): { start: Date; end: Date } {
  const raw = asString(month);
  if (!/^\d{4}-\d{2}$/.test(raw)) {
    throw new Error("month must be in YYYY-MM format.");
  }
  const year = Number(raw.slice(0, 4));
  const monthNumber = Number(raw.slice(5, 7));
  if (!Number.isFinite(year) || !Number.isFinite(monthNumber) || monthNumber < 1 || monthNumber > 12) {
    throw new Error("month must be in YYYY-MM format.");
  }
  const start = new Date(Date.UTC(year, monthNumber - 1, 1));
  const end = new Date(Date.UTC(year, monthNumber, 0));
  return { start, end };
}

function toIsoDate(dateValue: Date): string {
  return dateValue.toISOString().slice(0, 10);
}

function weekStartMonday(dateValue: Date): Date {
  const day = dateValue.getUTCDay();
  const offset = day === 0 ? -6 : 1 - day;
  const copy = new Date(dateValue);
  copy.setUTCDate(copy.getUTCDate() + offset);
  return copy;
}

function addDays(dateValue: Date, days: number): Date {
  const copy = new Date(dateValue);
  copy.setUTCDate(copy.getUTCDate() + days);
  return copy;
}

function scorePageHit(
  map: Map<string, { score: number; reasons: string[] }>,
  pageName: string,
  score: number,
  reason: string,
): void {
  const current = map.get(pageName) || { score: 0, reasons: [] };
  current.score += score;
  if (!current.reasons.includes(reason)) {
    current.reasons.push(reason);
  }
  map.set(pageName, current);
}

function toolResult(payload: AnyRecord): AnyRecord {
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    details: payload,
  };
}

function toolError(error: unknown): AnyRecord {
  const message = error instanceof Error ? error.message : String(error);
  return toolResult({ ok: false, error: message });
}

export default function register(api: {
  pluginConfig?: AnyRecord;
  registerTool: (tool: unknown, opts?: { optional?: boolean; names?: string[] }) => void;
}) {
  const pluginConfig = asRecord(api.pluginConfig);
  const defaultSearchLimit = Math.max(1, Math.min(50, Math.trunc(asNumber(pluginConfig.maxSearchResults, 12))));

  api.registerTool((ctx: { workspaceDir?: string }) => {
    const workspaceDir = asString(ctx.workspaceDir) || path.join(os.homedir(), ".openclaw", "workspace-maestro-solo");

    const withProject = <T extends AnyRecord>(handler: (project: ProjectRef, params: AnyRecord) => T) => {
      return (paramsRaw: unknown): AnyRecord => {
        try {
          const project = resolveProject(pluginConfig, workspaceDir);
          const params = asRecord(paramsRaw);
          return toolResult(handler(project, params));
        } catch (error) {
          return toolError(error);
        }
      };
    };

    const tools = [
      {
        name: `${TOOL_PREFIX}project_context`,
        description: "Return active project context and recommended workspace URLs.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {},
        },
        execute: (_id: string, params: unknown) =>
          withProject((project) => {
            const pages = listProjectPages(project);
            const awareness = resolveAwarenessUrls(workspaceDir);
            return {
              ok: true,
              project: {
                slug: project.slug,
                name: project.name,
                dir: project.dir,
                page_count: pages.length,
              },
              urls: awareness,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}list_pages`,
        description: "List project pages, optionally filtered by discipline.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            discipline: { type: "string" },
            limit: { type: "integer", minimum: 1, maximum: 400 },
          },
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const disciplineFilter = asString(payload.discipline).toLowerCase();
            const limit = Math.max(1, Math.min(400, Math.trunc(asNumber(payload.limit, 200))));
            const indexPages = asRecord(loadProjectIndex(project).pages);
            const names = listProjectPages(project);
            const rows = names
              .map((name) => {
                const meta = asRecord(indexPages[name]);
                return {
                  page_name: name,
                  discipline: asString(meta.discipline) || "General",
                  page_type: asString(meta.page_type) || "unknown",
                  region_count: Math.trunc(asNumber(meta.region_count, 0)),
                  pointer_count: Math.trunc(asNumber(meta.pointer_count, 0)),
                };
              })
              .filter((row) => (disciplineFilter ? row.discipline.toLowerCase() === disciplineFilter : true))
              .slice(0, limit);

            return {
              ok: true,
              project_slug: project.slug,
              count: rows.length,
              pages: rows,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}search`,
        description: "Search indexed project keywords/materials and score relevant sheets.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            query: { type: "string" },
            limit: { type: "integer", minimum: 1, maximum: 50 },
          },
          required: ["query"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const query = asString(payload.query);
            if (!query) {
              throw new Error("query is required.");
            }
            const limit = Math.max(1, Math.min(50, Math.trunc(asNumber(payload.limit, defaultSearchLimit))));
            const queryLower = query.toLowerCase();
            const index = loadProjectIndex(project);
            const scores = new Map<string, { score: number; reasons: string[] }>();

            const allPages = listProjectPages(project);
            for (const pageName of allPages) {
              if (pageName.toLowerCase().includes(queryLower)) {
                scorePageHit(scores, pageName, 5, "page_name");
              }
            }

            const keywords = asRecord(index.keywords);
            for (const [term, refsRaw] of Object.entries(keywords)) {
              if (!term.toLowerCase().includes(queryLower)) {
                continue;
              }
              if (!Array.isArray(refsRaw)) {
                continue;
              }
              for (const ref of refsRaw.slice(0, 80)) {
                const refPage = asString(asRecord(ref).page);
                if (refPage) {
                  scorePageHit(scores, refPage, 3, `keyword:${term}`);
                }
              }
            }

            const materials = asRecord(index.materials);
            for (const [term, refsRaw] of Object.entries(materials)) {
              if (!term.toLowerCase().includes(queryLower)) {
                continue;
              }
              if (!Array.isArray(refsRaw)) {
                continue;
              }
              for (const ref of refsRaw.slice(0, 80)) {
                const refPage = asString(asRecord(ref).page);
                if (refPage) {
                  scorePageHit(scores, refPage, 2, `material:${term}`);
                }
              }
            }

            const ranked = [...scores.entries()]
              .map(([pageName, meta]) => {
                const pass1 = loadPass1(project, pageName);
                return {
                  page_name: pageName,
                  score: meta.score,
                  reasons: meta.reasons.slice(0, 6),
                  discipline: asString(pass1.discipline) || "General",
                  summary: truncateText(pass1.sheet_reflection, 380),
                };
              })
              .sort((a, b) => b.score - a.score || a.page_name.localeCompare(b.page_name))
              .slice(0, limit);

            return {
              ok: true,
              project_slug: project.slug,
              query,
              count: ranked.length,
              results: ranked,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_sheet_summary`,
        description: "Return pass1 summary and core metadata for a sheet.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            page_name: { type: "string" },
          },
          required: ["page_name"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const pass1 = loadPass1(project, resolvedPage);
            const regions = Array.isArray(pass1.regions) ? pass1.regions : [];
            return {
              ok: true,
              project_slug: project.slug,
              page_name: resolvedPage,
              discipline: asString(pass1.discipline) || "General",
              page_type: asString(pass1.page_type) || "unknown",
              sheet_reflection: truncateText(pass1.sheet_reflection, 5000),
              region_count: regions.length,
              regions: regions.slice(0, 12).map((entry) => {
                const row = asRecord(entry);
                return {
                  id: asString(row.id),
                  label: asString(row.label),
                  detail_number: asString(row.detail_number),
                  type: asString(row.type),
                };
              }),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}list_regions`,
        description: "List available detail regions on a page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            page_name: { type: "string" },
            limit: { type: "integer", minimum: 1, maximum: 300 },
          },
          required: ["page_name"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const pass1 = loadPass1(project, resolvedPage);
            const regions = Array.isArray(pass1.regions) ? pass1.regions : [];
            const limit = Math.max(1, Math.min(300, Math.trunc(asNumber(payload.limit, 200))));
            const rows = regions.slice(0, limit).map((entry) => {
              const region = asRecord(entry);
              return {
                id: asString(region.id),
                label: asString(region.label),
                type: asString(region.type),
                detail_number: asString(region.detail_number),
                shows: truncateText(region.shows, 220),
                bbox: asRecord(region.bbox),
              };
            });
            return {
              ok: true,
              project_slug: project.slug,
              page_name: resolvedPage,
              count: rows.length,
              regions: rows,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_region_detail`,
        description: "Return structured pass2 detail for a specific region.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            page_name: { type: "string" },
            region_id: { type: "string" },
          },
          required: ["page_name", "region_id"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const regionId = asString(payload.region_id);
            if (!regionId) {
              throw new Error("region_id is required.");
            }
            const detail = loadPass2(project, resolvedPage, regionId);
            if (Object.keys(detail).length === 0) {
              throw new Error(`Region '${regionId}' not found on page '${resolvedPage}'.`);
            }

            return {
              ok: true,
              project_slug: project.slug,
              page_name: resolvedPage,
              region_id: regionId,
              content_markdown: truncateText(detail.content_markdown, 9000),
              materials: listSlice(detail.materials, 24),
              dimensions: listSlice(detail.dimensions, 24),
              keynotes: listSlice(detail.keynotes, 24),
              cross_references: listSlice(detail.cross_references, 24),
              coordination_notes: listSlice(detail.coordination_notes, 24),
              specifications: listSlice(detail.specifications, 24),
              questions_answered: listSlice(detail.questions_answered, 24),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}find_cross_references`,
        description: "Find outgoing and incoming references for a page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            page_name: { type: "string" },
            limit: { type: "integer", minimum: 1, maximum: 200 },
          },
          required: ["page_name"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const pass1 = loadPass1(project, resolvedPage);
            const outgoingRaw = Array.isArray(pass1.cross_references) ? pass1.cross_references : [];
            const outgoing = outgoingRaw
              .map((entry) => (typeof entry === "string" ? entry : asString(asRecord(entry).reference || asRecord(entry).sheet)))
              .filter((entry) => entry);

            const limit = Math.max(1, Math.min(200, Math.trunc(asNumber(payload.limit, 120))));
            const index = loadProjectIndex(project);
            const crossRefs = asRecord(index.cross_refs);
            const incoming: string[] = [];
            for (const [reference, pagesRaw] of Object.entries(crossRefs)) {
              if (!Array.isArray(pagesRaw)) {
                continue;
              }
              if (pagesRaw.some((item) => asString(item) === resolvedPage)) {
                incoming.push(reference);
              }
              if (incoming.length >= limit) {
                break;
              }
            }

            return {
              ok: true,
              project_slug: project.slug,
              page_name: resolvedPage,
              outgoing_references: outgoing.slice(0, limit),
              incoming_references: incoming.slice(0, limit),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}list_workspaces`,
        description: "List project workspaces.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {},
        },
        execute: (_id: string, params: unknown) =>
          withProject((project) => {
            const root = workspacesDir(project);
            const rows: AnyRecord[] = [];
            for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
              if (!entry.isDirectory()) {
                continue;
              }
              const payload = loadWorkspace(project, entry.name);
              if (!payload) {
                continue;
              }
              rows.push({
                slug: asString(payload.slug) || entry.name,
                title: asString(payload.title) || entry.name,
                description: asString(payload.description),
                page_count: Array.isArray(payload.pages) ? payload.pages.length : 0,
                note_count: Array.isArray(payload.notes) ? payload.notes.length : 0,
              });
            }
            rows.sort((a, b) => asString(a.title).localeCompare(asString(b.title)));
            return {
              ok: true,
              project_slug: project.slug,
              count: rows.length,
              workspaces: rows,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_workspace`,
        description: "Return full workspace payload by slug.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
          },
          required: ["workspace_slug"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            if (!workspaceSlug) {
              throw new Error("workspace_slug is required.");
            }
            const workspace = loadWorkspace(project, workspaceSlug);
            if (!workspace) {
              throw new Error(`Workspace '${workspaceSlug}' not found.`);
            }
            return {
              ok: true,
              project_slug: project.slug,
              workspace: workspace,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}create_workspace`,
        description: "Create a workspace (or return existing) by title/description.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            title: { type: "string" },
            description: { type: "string" },
            workspace_slug: { type: "string" },
          },
          required: ["title"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const title = asString(payload.title);
            const description = asString(payload.description);
            const requestedSlug = asString(payload.workspace_slug);
            if (!title) {
              throw new Error("title is required.");
            }
            const workspaceSlug = slugifyUnderscore(requestedSlug || title, "workspace");
            const existing = loadWorkspace(project, workspaceSlug);
            if (existing) {
              return {
                ok: true,
                created: false,
                project_slug: project.slug,
                workspace: existing,
              };
            }
            const workspace = ensureWorkspace(project, workspaceSlug, title, description);
            return {
              ok: true,
              created: true,
              project_slug: project.slug,
              workspace,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}add_page`,
        description: "Add a page to a workspace.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
          },
          required: ["workspace_slug", "page_name"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const workspace = ensureWorkspace(project, workspaceSlug, workspaceSlug, "");
            const pages = Array.isArray(workspace.pages) ? workspace.pages : [];
            workspace.pages = pages;
            const exists = pages.some((entry) => asString(asRecord(entry).page_name) === resolvedPage);
            if (!exists) {
              pages.push({
                page_name: resolvedPage,
                description: "",
                selected_pointers: [],
                highlights: [],
                custom_highlights: [],
              });
            }
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
              added: !exists,
              page_count: pages.length,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}remove_page`,
        description: "Remove a page from a workspace.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
          },
          required: ["workspace_slug", "page_name"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const workspace = loadWorkspace(project, workspaceSlug);
            if (!workspace) {
              throw new Error(`Workspace '${workspaceSlug}' not found.`);
            }
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const pages = Array.isArray(workspace.pages) ? workspace.pages : [];
            const filtered = pages.filter((entry) => asString(asRecord(entry).page_name) !== resolvedPage);
            workspace.pages = filtered;
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
              removed: filtered.length !== pages.length,
              page_count: filtered.length,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}select_pointers`,
        description: "Select one or more pass1 region IDs in a workspace page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
            pointer_ids: {
              type: "array",
              items: { type: "string" },
              minItems: 1,
            },
          },
          required: ["workspace_slug", "page_name", "pointer_ids"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const pointerIds = (Array.isArray(payload.pointer_ids) ? payload.pointer_ids : [])
              .map((item) => asString(item))
              .filter((item) => item);
            if (pointerIds.length === 0) {
              throw new Error("pointer_ids must include at least one id.");
            }
            const workspace = ensureWorkspace(project, workspaceSlug, workspaceSlug, "");
            const page = ensureWorkspacePage(workspace, resolvedPage);
            const selected = Array.isArray(page.selected_pointers) ? page.selected_pointers.map((item) => asString(item)).filter((item) => item) : [];
            const merged = Array.from(new Set([...selected, ...pointerIds]));
            page.selected_pointers = merged;
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
              selected_count: merged.length,
              selected_pointers: merged,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}deselect_pointers`,
        description: "Remove one or more selected pass1 region IDs from a workspace page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
            pointer_ids: {
              type: "array",
              items: { type: "string" },
              minItems: 1,
            },
          },
          required: ["workspace_slug", "page_name", "pointer_ids"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const workspace = loadWorkspace(project, workspaceSlug);
            if (!workspace) {
              throw new Error(`Workspace '${workspaceSlug}' not found.`);
            }
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const pointerIds = new Set(
              (Array.isArray(payload.pointer_ids) ? payload.pointer_ids : [])
                .map((item) => asString(item))
                .filter((item) => item),
            );
            const page = ensureWorkspacePage(workspace, resolvedPage);
            const selected = Array.isArray(page.selected_pointers) ? page.selected_pointers.map((item) => asString(item)).filter((item) => item) : [];
            const filtered = selected.filter((item) => !pointerIds.has(item));
            page.selected_pointers = filtered;
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
              selected_count: filtered.length,
              selected_pointers: filtered,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_project_notes`,
        description: "List project-level categorized notes and linked source pages.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {},
        },
        execute: (_id: string, params: unknown) =>
          withProject((project) => {
            const payload = loadProjectNotes(project);
            const categories = Array.isArray(payload.categories) ? payload.categories : [];
            const notes = Array.isArray(payload.notes) ? payload.notes : [];
            return {
              ok: true,
              project_slug: project.slug,
              category_count: categories.length,
              note_count: notes.length,
              updated_at: asString(payload.updated_at),
              categories,
              notes,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}upsert_note_category`,
        description: "Create/update a project-note category with a color.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            category_id: { type: "string" },
            name: { type: "string" },
            color: { type: "string" },
            order: { type: "integer" },
          },
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const requestedId = slugifyUnderscore(asString(payload.category_id), "");
            const name = asString(payload.name);
            const categoryId = requestedId || slugifyUnderscore(name, "");
            if (!categoryId) {
              throw new Error("category_id or name is required.");
            }

            const notesPayload = loadProjectNotes(project);
            const categories = Array.isArray(notesPayload.categories)
              ? notesPayload.categories.map((entry) => asRecord(entry))
              : [];
            const now = nowIso();

            const existingIndex = categories.findIndex((entry) => asString(entry.id) === categoryId);
            const previous = existingIndex >= 0 ? asRecord(categories[existingIndex]) : null;
            const category: AnyRecord = {
              id: categoryId,
              name: normalizeCategoryName(name || previous?.name, categoryId),
              color: normalizeNoteColor(payload.color || previous?.color),
              order: Number.isFinite(asNumber(payload.order, NaN))
                ? Math.trunc(asNumber(payload.order, 0))
                : Math.trunc(asNumber(previous?.order, categories.length * 10)),
              created_at: asString(previous?.created_at) || now,
              updated_at: now,
            };

            if (existingIndex >= 0) {
              categories[existingIndex] = category;
            } else {
              categories.push(category);
            }

            const saved = saveProjectNotes(project, {
              version: notesPayload.version,
              categories,
              notes: Array.isArray(notesPayload.notes) ? notesPayload.notes : [],
            });

            return {
              ok: true,
              project_slug: project.slug,
              category,
              category_count: Array.isArray(saved.categories) ? saved.categories.length : categories.length,
              updated_at: asString(saved.updated_at),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}add_note`,
        description: "Add/update a project-level note with optional category and source page links.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            text: { type: "string" },
            note_id: { type: "string" },
            category_id: { type: "string" },
            category_name: { type: "string" },
            color: { type: "string" },
            status: { type: "string" },
            pinned: { type: "boolean" },
            workspace_slug: { type: "string" },
            source_page: { type: "string" },
            source_pages: {
              type: "array",
              items: {
                type: "object",
                additionalProperties: false,
                properties: {
                  page_name: { type: "string" },
                  workspace_slug: { type: "string" },
                },
                required: ["page_name"],
              },
            },
          },
          required: ["text"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const text = asString(payload.text);
            if (!text) {
              throw new Error("text is required.");
            }

            const notesPayload = loadProjectNotes(project);
            const categories = Array.isArray(notesPayload.categories)
              ? notesPayload.categories.map((entry) => asRecord(entry))
              : [];
            const notes = Array.isArray(notesPayload.notes)
              ? notesPayload.notes.map((entry) => asRecord(entry))
              : [];
            const now = nowIso();

            let categoryId = slugifyUnderscore(asString(payload.category_id), "");
            const categoryName = asString(payload.category_name);
            if (!categoryId) {
              categoryId = slugifyUnderscore(categoryName, "");
            }
            if (!categoryId) {
              categoryId = "general";
            }

            let category = categories.find((entry) => asString(entry.id) === categoryId);
            if (!category) {
              category = {
                id: categoryId,
                name: normalizeCategoryName(categoryName, categoryId),
                color: normalizeNoteColor(payload.color),
                order: categories.length * 10,
                created_at: now,
                updated_at: now,
              };
              categories.push(category);
            } else {
              if (categoryName) category.name = categoryName;
              if (asString(payload.color)) category.color = normalizeNoteColor(payload.color);
              category.updated_at = now;
            }

            const fallbackWorkspaceSlug = slugifyUnderscore(asString(payload.workspace_slug), "");
            const sourcePages = normalizeSourcePages(payload, fallbackWorkspaceSlug);

            let noteId = slugifyUnderscore(asString(payload.note_id || payload.id), "");
            let existingIndex = -1;
            if (noteId) {
              existingIndex = notes.findIndex((entry) => asString(entry.id) === noteId);
            }
            if (!noteId) {
              const base = slugifyUnderscore(text.slice(0, 64), "note");
              noteId = `${base}_${Date.now().toString(36)}`;
            }
            const previous = existingIndex >= 0 ? asRecord(notes[existingIndex]) : null;

            const note: AnyRecord = {
              id: noteId,
              text,
              category_id: categoryId,
              source_pages: sourcePages,
              source_page: sourcePages.length ? asString(asRecord(sourcePages[0]).page_name) : "",
              pinned: asBoolean(payload.pinned, asBoolean(previous?.pinned, false)),
              status: normalizeNoteStatus(payload.status || previous?.status),
              created_at: asString(previous?.created_at) || now,
              updated_at: now,
            };

            if (existingIndex >= 0) {
              notes[existingIndex] = note;
            } else {
              notes.push(note);
            }

            const saved = saveProjectNotes(project, {
              version: notesPayload.version,
              categories,
              notes,
            });

            return {
              ok: true,
              project_slug: project.slug,
              created: existingIndex < 0,
              note_id: noteId,
              note,
              category,
              note_count: Array.isArray(saved.notes) ? saved.notes.length : notes.length,
              category_count: Array.isArray(saved.categories) ? saved.categories.length : categories.length,
              updated_at: asString(saved.updated_at),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}update_note_state`,
        description: "Update project-note lifecycle state (open/archived) and pinned flag without rewriting note text.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            note_id: { type: "string" },
            status: { type: "string" },
            pinned: { type: "boolean" },
          },
          required: ["note_id"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const noteId = slugifyUnderscore(asString(payload.note_id || payload.id), "");
            if (!noteId) {
              throw new Error("note_id is required.");
            }

            const hasStatus = typeof payload.status !== "undefined";
            const hasPinned = typeof payload.pinned !== "undefined";
            if (!hasStatus && !hasPinned) {
              throw new Error("Provide status and/or pinned.");
            }

            const notesPayload = loadProjectNotes(project);
            const categories = Array.isArray(notesPayload.categories)
              ? notesPayload.categories.map((entry) => asRecord(entry))
              : [];
            const notes = Array.isArray(notesPayload.notes)
              ? notesPayload.notes.map((entry) => asRecord(entry))
              : [];

            const targetIndex = notes.findIndex((entry) => asString(entry.id) === noteId);
            if (targetIndex < 0) {
              throw new Error(`Note '${noteId}' not found.`);
            }

            const now = nowIso();
            const target = asRecord(notes[targetIndex]);
            const updated: AnyRecord = {
              ...target,
              id: noteId,
              updated_at: now,
            };
            if (hasStatus) {
              updated.status = normalizeNoteStatus(payload.status);
            }
            if (hasPinned) {
              updated.pinned = asBoolean(payload.pinned, false);
            }

            notes[targetIndex] = updated;
            const saved = saveProjectNotes(project, {
              version: notesPayload.version,
              categories,
              notes,
            });

            return {
              ok: true,
              project_slug: project.slug,
              note_id: noteId,
              note: updated,
              note_count: Array.isArray(saved.notes) ? saved.notes.length : notes.length,
              updated_at: asString(saved.updated_at),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}add_description`,
        description: "Set/update description text for a workspace page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
            description: { type: "string" },
          },
          required: ["workspace_slug", "page_name", "description"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const description = asString(payload.description);
            if (!description) {
              throw new Error("description is required.");
            }
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const workspace = ensureWorkspace(project, workspaceSlug, workspaceSlug, "");
            const page = ensureWorkspacePage(workspace, resolvedPage);
            page.description = description;
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}set_custom_highlight`,
        description: "Create a custom highlight bbox on a workspace page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
            label: { type: "string" },
            query: { type: "string" },
            confidence: { type: "number" },
            bbox: {
              type: "object",
              additionalProperties: false,
              properties: {
                x0: { type: "number" },
                y0: { type: "number" },
                x1: { type: "number" },
                y1: { type: "number" },
              },
              required: ["x0", "y0", "x1", "y1"],
            },
          },
          required: ["workspace_slug", "page_name", "label", "bbox"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const label = asString(payload.label);
            const bbox = asRecord(payload.bbox);
            const x0 = asNumber(bbox.x0, NaN);
            const y0 = asNumber(bbox.y0, NaN);
            const x1 = asNumber(bbox.x1, NaN);
            const y1 = asNumber(bbox.y1, NaN);
            if (![x0, y0, x1, y1].every((item) => Number.isFinite(item))) {
              throw new Error("bbox must include finite x0,y0,x1,y1 values.");
            }
            const workspace = ensureWorkspace(project, workspaceSlug, workspaceSlug, "");
            const page = ensureWorkspacePage(workspace, resolvedPage);
            const custom = Array.isArray(page.custom_highlights) ? page.custom_highlights : [];
            page.custom_highlights = custom;
            custom.push({
              label,
              query: asString(payload.query),
              confidence: Number.isFinite(asNumber(payload.confidence, NaN)) ? asNumber(payload.confidence, NaN) : 0.75,
              bbox: { x0, y0, x1, y1 },
            });
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
              custom_highlight_count: custom.length,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}clear_custom_highlights`,
        description: "Clear all custom highlights for one workspace page.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            workspace_slug: { type: "string" },
            page_name: { type: "string" },
          },
          required: ["workspace_slug", "page_name"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const workspaceSlug = slugifyUnderscore(asString(payload.workspace_slug));
            const workspace = loadWorkspace(project, workspaceSlug);
            if (!workspace) {
              throw new Error(`Workspace '${workspaceSlug}' not found.`);
            }
            const resolvedPage = resolvePageName(project, asString(payload.page_name));
            const page = ensureWorkspacePage(workspace, resolvedPage);
            page.custom_highlights = [];
            saveWorkspace(project, workspaceSlug, workspace);
            return {
              ok: true,
              project_slug: project.slug,
              workspace_slug: workspaceSlug,
              page_name: resolvedPage,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_schedule_status`,
        description: "Return project-wide managed schedule status counts and file path.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {},
        },
        execute: (_id: string, params: unknown) =>
          withProject((project) => {
            const schedule = loadSchedule(project);
            const items = Array.isArray(schedule.items) ? schedule.items : [];
            const statusCounts: Record<string, number> = {
              pending: 0,
              in_progress: 0,
              blocked: 0,
              done: 0,
              cancelled: 0,
            };
            for (const item of items) {
              const status = normalizeScheduleStatus(asRecord(item).status);
              statusCounts[status] = (statusCounts[status] || 0) + 1;
            }
            return {
              ok: true,
              project_slug: project.slug,
              schedule_file: scheduleFilePath(project),
              updated_at: asString(schedule.updated_at),
              item_count: items.length,
              status_counts: statusCounts,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_schedule_timeline`,
        description: "Return day-by-day schedule timeline for a month.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            month: { type: "string", description: "YYYY-MM" },
            include_empty_days: { type: "boolean" },
          },
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const includeEmptyDays = payload.include_empty_days !== false;
            const today = new Date();
            const monthKey = asString(payload.month) || `${today.getUTCFullYear()}-${String(today.getUTCMonth() + 1).padStart(2, "0")}`;
            const bounds = monthBounds(monthKey);
            const schedule = loadSchedule(project);
            const items = Array.isArray(schedule.items) ? schedule.items : [];
            const dayMap = new Map<string, AnyRecord[]>();
            if (includeEmptyDays) {
              let cursor = new Date(bounds.start);
              while (cursor <= bounds.end) {
                dayMap.set(toIsoDate(cursor), []);
                cursor = addDays(cursor, 1);
              }
            }

            const unscheduled: AnyRecord[] = [];
            for (const item of items) {
              const row = asRecord(item);
              const dueDate = asString(row.due_date);
              const due = parseDate(dueDate);
              if (!due) {
                unscheduled.push(row);
                continue;
              }
              if (due < bounds.start || due > bounds.end) {
                continue;
              }
              const key = toIsoDate(due);
              const list = dayMap.get(key) || [];
              list.push({
                id: asString(row.id),
                title: asString(row.title),
                description: asString(row.description || row.notes),
                date: dueDate,
                due_date: dueDate,
                status: normalizeScheduleStatus(row.status),
                owner: asString(row.owner),
                type: normalizeScheduleType(row.type),
                activity_id: asString(row.activity_id),
                updated_at: asString(row.updated_at),
              });
              dayMap.set(key, list);
            }

            const dayRows = [...dayMap.entries()]
              .sort((a, b) => b[0].localeCompare(a[0]))
              .map(([dayKey, dayItems]) => {
                const dayDate = new Date(`${dayKey}T00:00:00Z`);
                const weekStart = weekStartMonday(dayDate);
                const dayLabel = dayDate.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
                return {
                  date: dayKey,
                  label: dayLabel,
                  is_today: dayKey === toIsoDate(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))),
                  is_future: dayKey > toIsoDate(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))),
                  is_past: dayKey < toIsoDate(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))),
                  week_start: toIsoDate(weekStart),
                  week_end: toIsoDate(addDays(weekStart, 6)),
                  week_label: `Week of ${weekStart.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}`,
                  item_count: dayItems.length,
                  items: dayItems,
                };
              });

            const previousMonth = new Date(Date.UTC(bounds.start.getUTCFullYear(), bounds.start.getUTCMonth() - 1, 1));
            const nextMonth = new Date(Date.UTC(bounds.start.getUTCFullYear(), bounds.start.getUTCMonth() + 1, 1));

            return {
              ok: true,
              project_slug: project.slug,
              today: toIsoDate(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))),
              month: monthKey,
              month_label: bounds.start.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }),
              month_start: toIsoDate(bounds.start),
              month_end: toIsoDate(bounds.end),
              previous_month: `${previousMonth.getUTCFullYear()}-${String(previousMonth.getUTCMonth() + 1).padStart(2, "0")}`,
              next_month: `${nextMonth.getUTCFullYear()}-${String(nextMonth.getUTCMonth() + 1).padStart(2, "0")}`,
              include_empty_days: includeEmptyDays,
              week_starts_on: "monday",
              sort_order: "future_to_past",
              updated_at: asString(schedule.updated_at),
              day_count: dayRows.length,
              item_count: dayRows.reduce((sum, dayRow) => sum + Math.trunc(asNumber(dayRow.item_count, 0)), 0) + unscheduled.length,
              days: dayRows,
              unscheduled: unscheduled.slice(0, 50),
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}list_schedule_items`,
        description: "List project schedule items, optionally filtered by status.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            status: { type: "string" },
            limit: { type: "integer", minimum: 1, maximum: 500 },
          },
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const statusFilterRaw = asString(payload.status);
            const statusFilter = statusFilterRaw ? normalizeScheduleStatus(statusFilterRaw) : "";
            const limit = Math.max(1, Math.min(500, Math.trunc(asNumber(payload.limit, 300))));
            const schedule = loadSchedule(project);
            const items = Array.isArray(schedule.items) ? schedule.items : [];
            const rows = items
              .filter((entry) => {
                if (!statusFilter) {
                  return true;
                }
                return normalizeScheduleStatus(asRecord(entry).status) === statusFilter;
              })
              .sort((a, b) => asString(asRecord(a).due_date).localeCompare(asString(asRecord(b).due_date)))
              .slice(0, limit);
            return {
              ok: true,
              project_slug: project.slug,
              count: rows.length,
              updated_at: asString(schedule.updated_at),
              items: rows,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}upsert_schedule_item`,
        description: "Create/update a managed schedule item.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            item_id: { type: "string" },
            title: { type: "string" },
            type: { type: "string" },
            status: { type: "string" },
            due_date: { type: "string" },
            owner: { type: "string" },
            activity_id: { type: "string" },
            impact: { type: "string" },
            notes: { type: "string" },
            description: { type: "string" },
          },
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const result = upsertScheduleItem(project, payload);
            return {
              ok: true,
              project_slug: project.slug,
              created: result.created,
              item: result.item,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}set_schedule_constraint`,
        description: "Create/update a schedule constraint item.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            constraint_id: { type: "string" },
            description: { type: "string" },
            activity_id: { type: "string" },
            impact: { type: "string" },
            due_date: { type: "string" },
            owner: { type: "string" },
            status: { type: "string" },
            notes: { type: "string" },
          },
          required: ["description"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const description = asString(payload.description);
            if (!description) {
              throw new Error("description is required.");
            }
            const constraintId = slugifyUnderscore(asString(payload.constraint_id) || description, "constraint");
            const result = upsertScheduleItem(project, {
              item_id: constraintId,
              title: description,
              type: "constraint",
              status: asString(payload.status) || "blocked",
              activity_id: asString(payload.activity_id),
              impact: asString(payload.impact),
              due_date: asString(payload.due_date),
              owner: asString(payload.owner),
              notes: asString(payload.notes),
            });
            return {
              ok: true,
              project_slug: project.slug,
              created: result.created,
              item: result.item,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}close_schedule_item`,
        description: "Close schedule item as done/cancelled.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            item_id: { type: "string" },
            status: { type: "string" },
            reason: { type: "string" },
          },
          required: ["item_id"],
        },
        execute: (_id: string, params: unknown) =>
          withProject((project, payload) => {
            const itemId = slugifyUnderscore(asString(payload.item_id), "");
            if (!itemId) {
              throw new Error("item_id is required.");
            }
            const closeStatus = normalizeScheduleStatus(asString(payload.status) || "done");
            if (closeStatus !== "done" && closeStatus !== "cancelled") {
              throw new Error("status must be done or cancelled.");
            }
            const schedule = loadSchedule(project);
            const items = Array.isArray(schedule.items) ? [...schedule.items] : [];
            const targetIndex = items.findIndex((entry) => asString(asRecord(entry).id) === itemId);
            if (targetIndex < 0) {
              throw new Error(`Schedule item '${itemId}' not found.`);
            }
            const now = nowIso();
            const target = asRecord(items[targetIndex]);
            target.status = closeStatus;
            target.closed_at = now;
            target.updated_at = now;
            target.close_reason = asString(payload.reason);
            items[targetIndex] = target;
            schedule.items = items;
            saveSchedule(project, schedule);
            return {
              ok: true,
              project_slug: project.slug,
              item: target,
            };
          })(params),
      },
      {
        name: `${TOOL_PREFIX}get_access_urls`,
        description: "Return recommended, tailnet, and localhost workspace URLs.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {},
        },
        execute: (_id: string, params: unknown) => {
          try {
            const urls = resolveAwarenessUrls(workspaceDir);
            return toolResult({ ok: true, ...urls });
          } catch (error) {
            return toolError(error);
          }
        },
      },
    ];

    return tools;
  });
}
