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
  for (const ack of payload.acks) {
    if (ack.status === "applied" || ack.status === "rejected") {
      await removeQueuedOperation(ack.operation_id);
    }
  }
  return payload.acks.every((ack) => ack.status === "applied");
}

function renderResumeCard(draft) {
  const card = document.getElementById("resume-card");
  if (!card || !draft) {
    return;
  }
  card.innerHTML = `
    <p>Local draft: ${draft.workout_type} started ${draft.started_at}</p>
    <a href="/workouts/${draft.workout_id}">Resume current draft</a>
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
}

async function triggerExternalSync() {
  const response = await fetch("/api/external/sync", { method: "POST" });
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  const syncStatus = document.getElementById("sync-status-placeholder");
  if (syncStatus) {
    syncStatus.textContent = `Garmin status: ${payload.last_status || "idle"}${payload.last_error ? ` (${payload.last_error})` : ""}`;
  }
  const imports = document.getElementById("pending-imports-placeholder");
  if (imports && payload.changed_pending_imports.length > 0) {
    imports.innerHTML = payload.changed_pending_imports
      .map((item) => `<p>Pending import ${item.provider_activity_id}: ${item.status}</p>`)
      .join("");
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
  imports.innerHTML = payload.items
    .map(
      (item) => `
        <div class="status" data-external-id="${item.id}">
          <p>${item.activity_type} at ${item.started_at}</p>
          <div class="grid">
            <button type="button" class="accept-import" data-external-id="${item.id}">Accept</button>
            <button type="button" class="dismiss-import" data-external-id="${item.id}">Dismiss</button>
            <input type="text" class="link-workout-id" placeholder="Workout UUID">
            <button type="button" class="link-import" data-external-id="${item.id}">Link</button>
          </div>
        </div>
      `,
    )
    .join("");
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
    await fetch(`/api/external/pending-imports/${externalId}/link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workout_id: workoutId }),
    });
  } else {
    return;
  }
  await refreshPendingImports();
}

function nowIso() {
  return new Date().toISOString();
}

function newUuid() {
  return crypto.randomUUID();
}

async function startWorkout(event) {
  event.preventDefault();
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
}

document.getElementById("start-workout-form")?.addEventListener("submit", startWorkout);
document.getElementById("sync-now")?.addEventListener("click", () => {
  void triggerExternalSync();
});
document.getElementById("pending-imports-placeholder")?.addEventListener("click", (event) => {
  void handlePendingImportAction(event);
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
