const DB_NAME = "workout-companion";
const DB_VERSION = 1;
const ACTIVE_DRAFT_STORE = "active_workout_drafts";
const PENDING_DRAFT_STORE = "pending_draft_creation";

function openWorkoutDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(ACTIVE_DRAFT_STORE)) {
        db.createObjectStore(ACTIVE_DRAFT_STORE, { keyPath: "workout_id" });
      }
      if (!db.objectStoreNames.contains(PENDING_DRAFT_STORE)) {
        db.createObjectStore(PENDING_DRAFT_STORE, { keyPath: "operation_id" });
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
  const transaction = db.transaction([ACTIVE_DRAFT_STORE, PENDING_DRAFT_STORE], "readwrite");
  transaction.objectStore(ACTIVE_DRAFT_STORE).put(draft);
  transaction.objectStore(PENDING_DRAFT_STORE).put(operation);
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
  const transaction = db.transaction(PENDING_DRAFT_STORE, "readonly");
  return txRequest(transaction.objectStore(PENDING_DRAFT_STORE).getAll());
}

async function removePendingDraft(operationId) {
  const db = await openWorkoutDb();
  const transaction = db.transaction(PENDING_DRAFT_STORE, "readwrite");
  transaction.objectStore(PENDING_DRAFT_STORE).delete(operationId);
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

async function attemptDraftCreation(operation) {
  if (!navigator.onLine) {
    return false;
  }
  const response = await fetch("/api/workouts/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(operation),
  });
  if (!response.ok) {
    return false;
  }
  await removePendingDraft(operation.operation_id);
  return true;
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
  for (const operation of pending) {
    try {
      await attemptDraftCreation(operation);
    } catch (_error) {
      // Keep the pending operation for later replay.
    }
  }
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
  const operation = {
    operation_id: newUuid(),
    workout_id: workoutId,
    type,
    started_at: nowIso(),
    client_timestamp: nowIso(),
  };
  const draft = {
    workout_id: workoutId,
    workout_type: type,
    status: "draft",
    started_at: operation.started_at,
    exercise_rows: [],
    set_rows: [],
    pending_operation_ids: [operation.operation_id],
    timer_state: null,
    last_local_write_at: operation.client_timestamp,
  };
  await saveLocalDraft(draft, operation);
  try {
    await attemptDraftCreation(operation);
  } catch (_error) {
    // Navigation should still proceed from local state.
  }
  window.location.assign(`/workouts/${workoutId}`);
}

document.getElementById("start-workout-form")?.addEventListener("submit", startWorkout);
window.addEventListener("online", () => {
  void hydrateDashboard();
});

window.workoutDraftStorage = {
  listLocalDrafts,
  openWorkoutDb,
};

void hydrateDashboard();
