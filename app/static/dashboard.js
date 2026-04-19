const DB_NAME = "workout-companion";
const DB_VERSION = 2;
const ACTIVE_DRAFT_STORE = "active_workout_drafts";
const OPERATION_QUEUE_STORE = "client_operation_queue";
const TIMER_STATE_STORE = "timer_state";
const CACHED_CONFIG_STORE = "cached_config";

function openWorkoutDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(ACTIVE_DRAFT_STORE)) {
        db.createObjectStore(ACTIVE_DRAFT_STORE, { keyPath: "workout_id" });
      }
      if (!db.objectStoreNames.contains(OPERATION_QUEUE_STORE)) {
        db.createObjectStore(OPERATION_QUEUE_STORE, { keyPath: "operation_id" });
      }
      if (!db.objectStoreNames.contains(TIMER_STATE_STORE)) {
        db.createObjectStore(TIMER_STATE_STORE, { keyPath: "workout_id" });
      }
      if (!db.objectStoreNames.contains(CACHED_CONFIG_STORE)) {
        db.createObjectStore(CACHED_CONFIG_STORE, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function txRequest(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveLocalDraft(draft, operation) {
  const db = await openWorkoutDb();
  const transaction = db.transaction([ACTIVE_DRAFT_STORE, OPERATION_QUEUE_STORE], "readwrite");
  transaction.objectStore(ACTIVE_DRAFT_STORE).put(draft);
  transaction.objectStore(OPERATION_QUEUE_STORE).put(operation);
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function listLocalDrafts() {
  const db = await openWorkoutDb();
  const transaction = db.transaction(ACTIVE_DRAFT_STORE, "readonly");
  return txRequest(transaction.objectStore(ACTIVE_DRAFT_STORE).getAll());
}

async function listPendingDraftOperations() {
  const db = await openWorkoutDb();
  const transaction = db.transaction(OPERATION_QUEUE_STORE, "readonly");
  return txRequest(transaction.objectStore(OPERATION_QUEUE_STORE).getAll());
}

async function removeQueuedOperation(operationId) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(OPERATION_QUEUE_STORE, "readwrite");
  transaction.objectStore(OPERATION_QUEUE_STORE).delete(operationId);
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function upsertDraftOnly(draft) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(ACTIVE_DRAFT_STORE, "readwrite");
  transaction.objectStore(ACTIVE_DRAFT_STORE).put(draft);
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function loadDraft(workoutId) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(ACTIVE_DRAFT_STORE, "readonly");
  return txRequest(transaction.objectStore(ACTIVE_DRAFT_STORE).get(workoutId));
}

async function queueOperation(operation) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(OPERATION_QUEUE_STORE, "readwrite");
  transaction.objectStore(OPERATION_QUEUE_STORE).put(operation);
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function cacheConfig(config) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(CACHED_CONFIG_STORE, "readwrite");
  transaction.objectStore(CACHED_CONFIG_STORE).put({ key: "config", value: config });
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function loadCachedConfig() {
  const db = await openWorkoutDb();
  const transaction = db.transaction(CACHED_CONFIG_STORE, "readonly");
  const record = await txRequest(transaction.objectStore(CACHED_CONFIG_STORE).get("config"));
  return record?.value || null;
}

async function saveTimerState(workoutId, state) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(TIMER_STATE_STORE, "readwrite");
  transaction.objectStore(TIMER_STATE_STORE).put({ workout_id: workoutId, ...state });
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function loadTimerState(workoutId) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(TIMER_STATE_STORE, "readonly");
  return txRequest(transaction.objectStore(TIMER_STATE_STORE).get(workoutId));
}

async function removeDraft(workoutId) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(ACTIVE_DRAFT_STORE, "readwrite");
  transaction.objectStore(ACTIVE_DRAFT_STORE).delete(workoutId);
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function reconcileDraftFromServer(workoutId, appliedStatuses, rejectedStatuses) {
  const draft = await loadDraft(workoutId);
  if (!draft) {
    return;
  }
  const remainingOperationIds = draft.pending_operation_ids.filter((id) => !appliedStatuses.has(id) && !rejectedStatuses.has(id));
  if (remainingOperationIds.length === 0 && draft.status === "finalized-pending-sync" && appliedStatuses.size > 0) {
    await removeDraft(workoutId);
    return;
  }

  let nextDraft = {
    ...draft,
    pending_operation_ids: remainingOperationIds,
  };
  if (remainingOperationIds.length === 0 && navigator.onLine) {
    const response = await fetch(`/api/workouts/${workoutId}`);
    if (response.ok) {
      const workout = await response.json();
      nextDraft = {
        ...nextDraft,
        workout_type: workout.type,
        status: workout.status,
        started_at: workout.started_at,
        set_rows: workout.sets.map((item) => ({
          id: item.id,
          exercise_name: item.exercise_name,
          sequence_index: item.sequence_index,
          weight_kg: item.weight_kg,
          reps: item.reps,
          duration_seconds: item.duration_seconds,
          set_type: item.set_type,
        })),
      };
    }
  }
  await upsertDraftOnly(nextDraft);
}

async function flushQueuedOperations() {
  if (!navigator.onLine) {
    return false;
  }
  const operations = await listPendingDraftOperations();
  if (operations.length === 0) {
    return true;
  }
  operations.sort((left, right) => left.client_timestamp.localeCompare(right.client_timestamp));
  const response = await fetch("/api/client-operations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operations }),
  });
  if (!response.ok) {
    return false;
  }
  const payload = await response.json();
  const resolvedOperationIds = new Set();
  const rejectedOperationIds = new Set();
  const affectedWorkoutIds = new Set();
  for (const ack of payload.acks) {
    if (ack.status === "applied") {
      resolvedOperationIds.add(ack.operation_id);
      await removeQueuedOperation(ack.operation_id);
    } else if (ack.status === "rejected") {
      rejectedOperationIds.add(ack.operation_id);
      await removeQueuedOperation(ack.operation_id);
    }
  }
  for (const operation of operations) {
    if (resolvedOperationIds.has(operation.operation_id) || rejectedOperationIds.has(operation.operation_id)) {
      affectedWorkoutIds.add(operation.workout_id);
    }
  }
  for (const workoutId of affectedWorkoutIds) {
    await reconcileDraftFromServer(workoutId, resolvedOperationIds, rejectedOperationIds);
  }
  return payload.acks.every((ack) => ack.status === "applied");
}

function renderResumeCard(draft) {
  const card = document.getElementById("resume-card");
  if (!card || !draft) {
    return;
  }
  card.innerHTML = `
    <p>Local draft: ${draft.workout_type.replaceAll("_", " ")} started ${formatDisplayDate(draft.started_at)}</p>
    <a href="/workouts/${draft.workout_id}">Resume current draft</a>
  `;
}

function formatDisplayDate(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  const formatter = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = Object.fromEntries(formatter.formatToParts(parsed).map((part) => [part.type, part.value]));
  return `${parts.weekday}, ${parts.month} ${parts.day}, ${parts.year} at ${parts.hour}:${parts.minute}`;
}

function titleCaseWords(value) {
  return String(value || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function renderPendingImportCard(item) {
  const activityLabel = titleCaseWords(item.activity_type);
  const distance = item.distance_meters ?? 0;
  const duration = item.duration_seconds ?? 0;
  const candidateMarkup =
    item.candidate_workouts && item.candidate_workouts.length > 0
      ? `
        <select class="link-workout-id">
          ${item.candidate_workouts
            .map(
              (workout) => `
                <option value="${workout.id}" ${workout.id === item.suggested_workout_id ? "selected" : ""}>
                  ${titleCaseWords(workout.type)} · ${titleCaseWords(workout.status)} · ${formatDisplayDate(workout.started_at)}
                </option>
              `,
            )
            .join("")}
        </select>
        <button type="button" class="link-import soft-button" data-external-id="${item.id}">Link workout</button>
      `
      : `
        <span class="muted">No matching workout found</span>
        <button type="button" class="link-import soft-button" data-external-id="${item.id}" disabled>Link workout</button>
      `;
  /* Keep structure in sync with dashboard.html so CSS (.list-item, .pill-row, .grid.compact) stays consistent */
  return `
    <div class="list-item" data-external-id="${item.id}">
      <strong>${activityLabel}</strong>
      <p>${formatDisplayDate(item.started_at)}</p>
      <div class="pill-row">
        <span class="pill">${distance} m</span>
        <span class="pill">${duration} sec</span>
      </div>
      <div class="grid compact">
        <button type="button" class="accept-import" data-external-id="${item.id}">Accept</button>
        <button type="button" class="dismiss-import soft-button" data-external-id="${item.id}">Dismiss</button>
        ${candidateMarkup}
      </div>
    </div>
  `;
}

function formatDurationSeconds(value) {
  if (value == null) {
    return "n/a";
  }
  const totalSeconds = Number(value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatPace(value) {
  if (value == null) {
    return "n/a";
  }
  return `${formatDurationSeconds(Math.round(Number(value)))}/km`;
}

function renderAcceptedRunCard(item) {
  return `
    <article class="list-item accepted-run-card" data-workout-id="${item.workout_id}">
      <strong>${titleCaseWords(item.activity_type)}</strong>
      <p>${formatDisplayDate(item.started_at)}</p>
      <div class="pill-row">
        <span class="pill">${item.distance_meters ?? 0} m</span>
        <span class="pill">${item.duration_seconds ?? 0} sec</span>
        <span class="pill">Avg HR: ${item.avg_heart_rate ?? "n/a"}</span>
        <span class="pill">Max HR: ${item.max_heart_rate ?? "n/a"}</span>
        <span class="pill">Pace: ${formatPace(item.pace_seconds_per_km)}</span>
        <span class="pill">Calories: ${item.calories ?? "n/a"}</span>
        <span class="pill">Cal/min: ${item.calories_per_minute ?? "n/a"}</span>
      </div>
      <form class="accepted-run-form stack" data-workout-id="${item.workout_id}">
        <label>
          Feels
          <input type="number" name="feeling_score" min="1" max="5" step="1" value="${item.feeling_score ?? ""}">
        </label>
        <label>
          Notes
          <textarea name="notes" placeholder="How did the run feel?">${item.notes ?? ""}</textarea>
        </label>
        <div class="button-row">
          <button type="submit">Save reflection</button>
          <span class="muted accepted-run-status">Workout type: ${titleCaseWords(item.workout_type)}</span>
        </div>
      </form>
    </article>
  `;
}

async function hydrateDashboard() {
  const drafts = await listLocalDrafts();
  if (drafts.length > 0) {
    drafts.sort((left, right) => right.last_local_write_at.localeCompare(left.last_local_write_at));
    renderResumeCard(drafts[0]);
  }
  const pending = await listPendingDraftOperations();
  if (pending.length > 0) {
    try {
      await flushQueuedOperations();
    } catch (_error) {
      // Keep the pending operations for later replay.
    }
  }
  try {
    const response = await fetch("/api/config");
    if (response.ok) {
      await cacheConfig(await response.json());
    }
  } catch (_error) {
    // Use stale cached config when offline.
  }
  await refreshAcceptedRuns();
}

async function triggerExternalSync() {
  const syncButton = document.getElementById("sync-now");
  const syncStatus = document.getElementById("sync-status-placeholder");
  const originalLabel = syncButton?.textContent || "Sync now";
  if (syncButton) {
    syncButton.disabled = true;
    syncButton.classList.add("is-loading");
    syncButton.textContent = "Syncing";
  }
  try {
    const response = await fetch("/api/external/sync", { method: "POST" });
    if (!response.ok) {
      if (syncStatus) {
        syncStatus.textContent = "Sync failed.";
      }
      return;
    }
    const payload = await response.json();
    if (syncStatus) {
      syncStatus.textContent = payload.status_label || payload.last_status || "Garmin idle";
    }
    await refreshPendingImports();
    await refreshAcceptedRuns();
  } finally {
    if (syncButton) {
      syncButton.disabled = false;
      syncButton.classList.remove("is-loading");
      syncButton.textContent = originalLabel;
    }
  }
}

async function refreshPendingImports() {
  const response = await fetch("/api/external/pending-imports");
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  const imports = document.getElementById("pending-imports-placeholder");
  if (!imports) {
    return;
  }
  if (payload.items.length === 0) {
    imports.innerHTML = "<p>No pending imports yet.</p>";
    return;
  }
  imports.innerHTML = payload.items.map((item) => renderPendingImportCard(item)).join("");
}

async function refreshAcceptedRuns() {
  const response = await fetch("/api/external/accepted-runs");
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  const runs = document.getElementById("accepted-runs-placeholder");
  if (!runs) {
    return;
  }
  if (payload.items.length === 0) {
    runs.innerHTML = "<p>No accepted runs yet.</p>";
    return;
  }
  runs.innerHTML = payload.items.map((item) => renderAcceptedRunCard(item)).join("");
}

async function handlePendingImportAction(event) {
  const target = event.target.closest("button");
  if (!target) {
    return;
  }
  const externalId = target.dataset.externalId;
  if (!externalId) {
    return;
  }
  if (target.classList.contains("dismiss-import")) {
    await fetch(`/api/external/pending-imports/${externalId}/dismiss`, { method: "POST" });
  } else if (target.classList.contains("accept-import")) {
    await fetch(`/api/external/pending-imports/${externalId}/accept`, { method: "POST" });
  } else if (target.classList.contains("link-import")) {
    const container = target.closest("[data-external-id]");
    const workoutId = container?.querySelector(".link-workout-id")?.value;
    if (!workoutId) {
      return;
    }
    await fetch(`/api/external/pending-imports/${externalId}/link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workout_id: workoutId }),
    });
  } else {
    return;
  }
  await refreshPendingImports();
  await refreshAcceptedRuns();
}

async function saveAcceptedRunReflection(form) {
  const workoutId = form.dataset.workoutId;
  if (!workoutId) {
    return;
  }
  const formData = new FormData(form);
  const feelingScoreValue = formData.get("feeling_score");
  const notesValue = formData.get("notes");
  const response = await fetch(`/api/workouts/${workoutId}/reflection`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      feeling_score: feelingScoreValue ? Number(feelingScoreValue) : null,
      notes: notesValue ? String(notesValue) : null,
    }),
  });
  const statusNode = form.querySelector(".accepted-run-status");
  if (!response.ok) {
    if (statusNode) {
      statusNode.textContent = "Save failed.";
    }
    return;
  }
  const payload = await response.json();
  if (statusNode) {
    statusNode.textContent = `Saved. Workout type: ${titleCaseWords(payload.type)}`;
  }
  await refreshAcceptedRuns();
}

function nowIso() {
  return new Date().toISOString();
}

function newUuid() {
  const c = globalThis.crypto;
  if (c?.randomUUID) {
    try {
      return c.randomUUID();
    } catch {
      /* randomUUID() throws outside a secure context in some browsers */
    }
  }
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) {
    c.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i += 1) {
      bytes[i] = (Math.random() * 256) | 0;
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const h = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

async function startWorkout(event) {
  event.preventDefault();
  try {
    const type = document.getElementById("type-selector").value;
    const workoutId = newUuid();
    const timestamp = nowIso();
    const operation = {
      operation_id: newUuid(),
      workout_id: workoutId,
      operation_type: "create_draft",
      client_timestamp: timestamp,
      payload: {
        type,
        started_at: timestamp,
      },
    };
    const draft = {
      workout_id: workoutId,
      workout_type: type,
      status: "draft",
      started_at: timestamp,
      exercise_rows: [],
      set_rows: [],
      pending_operation_ids: [operation.operation_id],
      timer_state: null,
      last_local_write_at: operation.client_timestamp,
    };
    await saveLocalDraft(draft, operation);
    try {
      await flushQueuedOperations();
    } catch (_error) {
      // Navigation should still proceed from local state.
    }
    window.location.assign(`/workouts/${workoutId}`);
  } catch (error) {
    console.error("Start workout failed:", error);
    window.alert(
      "Could not start a workout. The site needs IndexedDB (site data) enabled. If you opened this app via a LAN IP (not localhost), your browser may block storage; try http://127.0.0.1 or http://localhost instead.",
    );
  }
}

document.getElementById("start-workout-form")?.addEventListener("submit", startWorkout);
document.getElementById("sync-now")?.addEventListener("click", () => {
  void triggerExternalSync();
});
document.getElementById("pending-imports-placeholder")?.addEventListener("click", (event) => {
  void handlePendingImportAction(event);
});
document.getElementById("accepted-runs-placeholder")?.addEventListener("submit", (event) => {
  const form = event.target.closest(".accepted-run-form");
  if (!form) {
    return;
  }
  event.preventDefault();
  void saveAcceptedRunReflection(form);
});
window.addEventListener("online", () => {
  void hydrateDashboard();
});

window.workoutDraftStorage = {
  cacheConfig,
  flushQueuedOperations,
  listPendingOperations: listPendingDraftOperations,
  listLocalDrafts,
  loadCachedConfig,
  loadDraft,
  loadTimerState,
  openWorkoutDb,
  queueOperation,
  removeDraft,
  saveTimerState,
  upsertDraftOnly,
};

void hydrateDashboard();
