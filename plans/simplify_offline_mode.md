Here is a detailed development plan for replacing the operation-queue architecture with direct server writes and an offline fallback.

---

## Architecture Overview

The key insight is that the server already has all the REST endpoints needed for direct writes. `PUT /api/workouts/<id>/sets/<set_id>`, `DELETE /api/workouts/<id>/sets/<set_id>`, `POST /api/workouts/draft`, and `POST /api/workouts/<id>/finalize` all exist and are fully functional. [1](#1-0) 

The current operation queue was a **client-side architectural choice**, not a server requirement. The server's `client_operation_log` idempotency checks already work with direct calls via `_prior_operation()`. [2](#1-1) 

---

## New Mental Model

```
User action
  → optimistic in-memory UI update (instant feedback)
  → attempt direct HTTP write to existing REST endpoint
      ├── success → confirm/correct UI from server response
      └── failure (offline/network) → push to offline_queue in IndexedDB
                                       keep optimistic state in memory

window "online" event
  → drain offline_queue in insertion order
      ├── each success → remove from queue
      └── each failure → stop draining, retry later
```

---

## Phase 1: Server-Side Cleanup

### 1.1 Remove `/api/client-operations`

Delete `app/queue_service.py` entirely and remove the `post_client_operations` route from `app/routes_workouts.py`. [3](#1-2) [4](#1-3) 

The `client_operation_log` table in `schema.sql` **must be kept** — the direct REST endpoints (`upsert_set`, `delete_set`, `finalize_workout`) all write to it for idempotency. No schema change needed. [5](#1-4) 

### 1.2 Ensure `operation_id` is accepted on direct endpoints

The existing `PUT /api/workouts/<id>/sets/<set_id>` and `DELETE` endpoints already accept `operation_id` in the request body and check `_prior_operation()`. Verify the finalize endpoint does the same. [6](#1-5) [7](#1-6) 

No changes needed here — this already works.

---

## Phase 2: IndexedDB Restructure (`dashboard.js`)

### 2.1 Bump DB version and migrate stores

Change `DB_VERSION` from `2` to `3`. In `onupgradeneeded`, delete the old stores and create the new one: [8](#1-7) 

```js
const DB_VERSION = 3;
const TIMER_STATE_STORE = "timer_state";       // keep unchanged
const CACHED_CONFIG_STORE = "cached_config";   // keep unchanged
const OFFLINE_QUEUE_STORE = "offline_queue";   // NEW — replaces both old stores

request.onupgradeneeded = (event) => {
  const db = request.result;
  // Delete old stores if upgrading from v2
  if (event.oldVersion < 3) {
    if (db.objectStoreNames.contains("active_workout_drafts")) {
      db.deleteObjectStore("active_workout_drafts");
    }
    if (db.objectStoreNames.contains("client_operation_queue")) {
      db.deleteObjectStore("client_operation_queue");
    }
  }
  if (!db.objectStoreNames.contains(TIMER_STATE_STORE)) {
    db.createObjectStore(TIMER_STATE_STORE, { keyPath: "workout_id" });
  }
  if (!db.objectStoreNames.contains(CACHED_CONFIG_STORE)) {
    db.createObjectStore(CACHED_CONFIG_STORE, { keyPath: "key" });
  }
  if (!db.objectStoreNames.contains(OFFLINE_QUEUE_STORE)) {
    const store = db.createObjectStore(OFFLINE_QUEUE_STORE, { keyPath: "id", autoIncrement: true });
    store.createIndex("by_created_at", "created_at");
  }
};
```

### 2.2 New offline queue API (replaces ~150 lines of draft/queue functions)

Replace all draft and queue functions with these three:

```js
// Each entry: { method, url, body_json, created_at, idempotency_key }
async function pushOfflineRequest(method, url, body) {
  const db = await openWorkoutDb();
  const tx = db.transaction(OFFLINE_QUEUE_STORE, "readwrite");
  tx.objectStore(OFFLINE_QUEUE_STORE).add({
    method,
    url,
    body_json: JSON.stringify(body),
    created_at: new Date().toISOString(),
    idempotency_key: body.operation_id || null,
  });
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function listOfflineQueue() {
  const db = await openWorkoutDb();
  const tx = db.transaction(OFFLINE_QUEUE_STORE, "readonly");
  return txRequest(tx.objectStore(OFFLINE_QUEUE_STORE).index("by_created_at").getAll());
}

async function removeOfflineEntry(id) {
  const db = await openWorkoutDb();
  const tx = db.transaction(OFFLINE_QUEUE_STORE, "readwrite");
  tx.objectStore(OFFLINE_QUEUE_STORE).delete(id);
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
```

### 2.3 New drain function (replaces `flushQueuedOperations` and `reconcileDraftFromServer`)

```js
async function drainOfflineQueue() {
  if (!navigator.onLine) return;
  const entries = await listOfflineQueue();
  for (const entry of entries) {
    try {
      const response = await fetch(entry.url, {
        method: entry.method,
        headers: { "Content-Type": "application/json" },
        body: entry.body_json,
      });
      if (response.ok || response.status === 409) {
        // 409 = already applied (idempotency), safe to remove
        await removeOfflineEntry(entry.id);
      } else {
        // Server rejected — log and remove to avoid blocking the queue
        console.warn("Offline queue entry rejected by server", entry, response.status);
        await removeOfflineEntry(entry.id);
      }
    } catch (_networkError) {
      // Still offline — stop draining, leave remaining entries
      break;
    }
  }
}
```

Note: The decision to remove rejected entries (vs. keeping them) is a tradeoff discussed below.

### 2.4 Update `window.workoutDraftStorage` export

Replace the exported API:

```js
window.workoutDraftStorage = {
  cacheConfig,
  loadCachedConfig,
  loadTimerState,
  openWorkoutDb,
  saveTimerState,
  pushOfflineRequest,
  drainOfflineQueue,
};
```

### 2.5 Update `startWorkout` in `dashboard.js`

```js
async function startWorkout(event) {
  event.preventDefault();
  const type = document.getElementById("type-selector").value;
  const workoutId = newUuid();
  const operationId = newUuid();
  const timestamp = nowIso();
  const body = {
    operation_id: operationId,
    workout_id: workoutId,
    type,
    started_at: timestamp,
    client_timestamp: timestamp,
  };
  try {
    const response = await fetch("/api/workouts/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok && response.status !== 409) {
      throw new Error("server rejected draft creation");
    }
  } catch (_error) {
    // Offline: queue the creation and navigate anyway.
    // WARNING: page reload while offline will show "workout not found".
    await window.workoutDraftStorage.pushOfflineRequest("POST", "/api/workouts/draft", body);
  }
  window.location.assign(`/workouts/${workoutId}`);
}
```

### 2.6 Update `hydrateDashboard`

Remove all draft/queue logic. The dashboard no longer shows a "resume draft" card (no local drafts exist). Replace with a simple offline queue indicator:

```js
async function hydrateDashboard() {
  const pending = await listOfflineQueue();
  const indicator = document.getElementById("offline-queue-indicator");
  if (indicator) {
    indicator.textContent = pending.length > 0
      ? `${pending.length} action(s) pending sync`
      : "";
  }
  if (pending.length > 0) {
    await drainOfflineQueue();
  }
  try {
    const response = await fetch("/api/config");
    if (response.ok) await cacheConfig(await response.json());
  } catch (_error) { /* use stale cache */ }
  await refreshAcceptedRuns();
}
```

Remove `renderResumeCard` entirely. [9](#1-8) 

---

## Phase 3: Rewrite `workout.js`

### 3.1 Replace draft-based state with in-memory state

Remove `mutateLocalDraft`, `loadWorkoutShell` (draft branch), and all `workoutDraftStorage.loadDraft` calls.

Add an in-memory state object at module scope:

```js
let _workoutState = null; // populated from server on page load

function getWorkoutState() { return _workoutState; }

function applyOptimisticUpdate(mutator) {
  if (_workoutState) {
    _workoutState = mutator(structuredClone(_workoutState));
    renderWorkoutFromState(_workoutState);
  }
}

function confirmFromServer(serverData) {
  _workoutState = serverData;
  renderWorkoutFromState(_workoutState);
}
```

### 3.2 New `renderWorkoutFromState`

Consolidate the two rendering paths (local draft vs. server) into one function that accepts the state object:

```js
function renderWorkoutFromState(state) {
  document.getElementById("workout-title").textContent =
    `${formatWorkoutType(state.type)} Workout`;
  const list = document.getElementById("set-list");
  if (list) {
    list.innerHTML = state.sets.length
      ? state.sets
          .slice()
          .sort((a, b) => a.sequence_index - b.sequence_index)
          .map(setListItemHtml)
          .join("")
      : '<div class="list-item"><p>No sets logged yet.</p></div>';
  }
  // render shell tiles: type, status, started_at
}
```

This replaces the dual-path logic in `refreshWorkout` and `loadWorkoutShell`. [10](#1-9) 

### 3.3 Rewrite `upsertSet`

```js
async function upsertSet(event) {
  event.preventDefault();
  const workoutId = currentWorkoutId();
  const setId = document.getElementById("set-id").value || newUuid();
  document.getElementById("set-id").value = setId;
  const operationId = newUuid();
  const body = {
    operation_id: operationId,
    operation_type: "upsert_set",
    client_timestamp: new Date().toISOString(),
    exercise_name: document.getElementById("exercise-name").value,
    sequence_index: Number(document.getElementById("sequence-index").value),
    weight_kg: document.getElementById("weight-kg").value
      ? Number(document.getElementById("weight-kg").value) : null,
    reps: document.getElementById("reps").value
      ? Number(document.getElementById("reps").value) : null,
    duration_seconds: document.getElementById("duration-seconds").value
      ? Number(document.getElementById("duration-seconds").value) : null,
    set_type: document.getElementById("set-type").value,
  };

  // Optimistic update
  applyOptimisticUpdate((state) => {
    const idx = state.sets.findIndex((s) => s.id === setId);
    const next = { id: setId, ...body };
    if (idx >= 0) state.sets[idx] = next; else state.sets.push(next);
    return state;
  });

  try {
    const response = await fetch(`/api/workouts/${workoutId}/sets/${setId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.ok) {
      const payload = await response.json();
      // Confirm with server-authoritative data
      applyOptimisticUpdate((state) => {
        const idx = state.sets.findIndex((s) => s.id === setId);
        if (idx >= 0) state.sets[idx] = payload.set; else state.sets.push(payload.set);
        return state;
      });
    } else {
      // Server rejected (validation error) — revert optimistic update
      const serverResponse = await fetch(`/api/workouts/${workoutId}`);
      if (serverResponse.ok) confirmFromServer(await serverResponse.json());
    }
  } catch (_networkError) {
    await window.workoutDraftStorage.pushOfflineRequest(
      "PUT", `/api/workouts/${workoutId}/sets/${setId}`, body
    );
    // Optimistic state stays in memory
  }
}
```

### 3.4 Rewrite `deleteSelectedSet` similarly

Same pattern: optimistic remove from `_workoutState.sets`, attempt `DELETE /api/workouts/{id}/sets/{setId}`, on network failure push to offline queue.

### 3.5 Update `window.online` handler

```js
window.addEventListener("online", () => {
  void window.workoutDraftStorage.drainOfflineQueue();
});
```

### 3.6 Update page initialization

```js
async function initWorkoutPage() {
  const workoutId = currentWorkoutId();
  const response = await fetch(`/api/workouts/${workoutId}`);
  if (response.ok) {
    _workoutState = await response.json();
    renderWorkoutFromState(_workoutState);
  } else {
    // Workout not yet on server (created offline) — show pending state
    document.getElementById("workout-shell").innerHTML =
      "<p>Workout pending sync. Actions will be queued.</p>";
  }
  await renderTimer();
  // Drain any queued operations from a previous offline session
  await window.workoutDraftStorage.drainOfflineQueue();
}

void initWorkoutPage();
```

---

## Phase 4: Rewrite `summary.js`

```js
async function finalizeWorkout(event) {
  event.preventDefault();
  const workoutId = window.__summaryPage.workoutId;
  const operationId = newUuid();
  const body = {
    operation_id: operationId,
    operation_type: "finalize_workout",
    client_timestamp: new Date().toISOString(),
    ended_at: new Date().toISOString(),
    feeling_score: Number(document.getElementById("feeling-score").value),
    notes: document.getElementById("workout-notes").value || null,
  };
  const statusEl = document.getElementById("finalize-status");
  try {
    const response = await fetch(`/api/workouts/${workoutId}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.ok) {
      statusEl.textContent = "Workout finalized.";
    } else {
      const err = await response.json();
      statusEl.textContent = `Error: ${err.error}`;
    }
  } catch (_networkError) {
    await window.workoutDraftStorage.pushOfflineRequest(
      "POST", `/api/workouts/${workoutId}/finalize`, body
    );
    statusEl.textContent = "Finalized locally. Will sync when online.";
  }
}
```

Remove the `finalized-pending-sync` status entirely — it was a client-only concept. [11](#1-10) 

---

## Phase 5: Test Updates

The existing tests in `tests/` cover `queue_service.py` and the `/api/client-operations` endpoint. These need to be deleted. The direct REST endpoint tests (`put_set`, `delete_set_route`, `post_finalize`) should already exist and continue to pass unchanged.


Add a new test: verify that `PUT /api/workouts/<id>/sets/<set_id>` with a duplicate `operation_id` returns `200` with the previously-applied result (idempotency regression test).

---

## Tradeoffs

| Concern | Current System | New System |
|---|---|---|
| **Offline workout start** | Full support — draft survives page reload | Workout state lost on page reload while offline. Navigation still works but reload shows "pending sync" shell. |
| **Set logging offline** | Sets survive page reload (IndexedDB draft) | Sets are in-memory only. Page reload while offline loses unsynced sets. |
| **Code complexity** | ~215 lines of queue/reconcile logic in `dashboard.js` alone | ~50 lines of offline queue logic. No reconciliation. |
| **State source of truth** | Dual: local draft + server, complex merge | Single: server. Client is a view. |
| **Error visibility** | Boolean flush result, no per-operation errors shown | Per-request HTTP status, can show specific validation errors inline. |
| **Idempotency** | Preserved via `operation_id` in queue | Preserved via `operation_id` sent on every direct write and retry. |
| **Rejected operations** | Kept in queue with `rejected` status | Removed from queue after server rejection (unrecoverable). |
| **`client_operation_log` table** | Used for idempotency + audit | Still used for idempotency. Audit log is a free side-effect. |
| **Finalize race condition** | `finalized-pending-sync` state can persist indefinitely | No intermediate state. Either finalized on server or queued. |

### The critical offline regression

The most significant regression is **set logging during an offline session does not survive a page reload**. For a self-hosted single-user app where the server is typically on the same LAN, this is an acceptable tradeoff. However, it should be documented prominently in the UI: show a banner like "You are offline — unsaved sets will be lost if you reload" when `navigator.onLine` is false.

### Rejected operations in the offline queue

The plan above removes rejected entries from the queue. An alternative is to surface them to the user (e.g., "1 action failed to sync — tap to review"). For a workout app, a rejected set upsert is almost always a validation error that the user needs to fix manually, so silent removal with a console warning is reasonable. This decision should be revisited if the app gains more complex mutation types.

### Citations

**File:** app/routes_workouts.py (L68-78)
```python
@workouts_bp.post("/api/client-operations")
def post_client_operations():
    payload = request.get_json(silent=True) or {}
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return jsonify({"error": "operations must be a list"}), HTTPStatus.BAD_REQUEST
    try:
        acks = process_operation_batch(get_db(), operations)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify({"acks": acks})
```

**File:** app/routes_workouts.py (L161-186)
```python
@workouts_bp.put("/api/workouts/<workout_id>/sets/<set_id>")
def put_set(workout_id: str, set_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = upsert_set(get_db(), workout_id, set_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code


@workouts_bp.delete("/api/workouts/<workout_id>/sets/<set_id>")
def delete_set_route(workout_id: str, set_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = delete_set(get_db(), workout_id, set_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code
```

**File:** app/set_service.py (L28-36)
```python
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    validate_uuid(workout_id, "workout_id")
    validate_uuid(set_id, "set_id")
    _load_mutable_workout(connection, workout_id)
    prior = _prior_operation(connection, operation_id)
    if prior:
        if prior["status"] == "applied":
            return MutationResult(HTTPStatus.OK, {"set": get_set_payload(connection, set_id)})
        raise ValueError(prior["error_message"] or "operation previously rejected")
```

**File:** app/set_service.py (L234-237)
```python
def _prior_operation(connection: sqlite3.Connection, operation_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT status, error_message FROM client_operation_log WHERE operation_id = ?",
        (operation_id,),
```

**File:** app/queue_service.py (L15-18)
```python
def process_operation_batch(
    connection: sqlite3.Connection, operations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [process_operation(connection, operation) for operation in operations]
```

**File:** app/schema.sql (L91-101)
```sql
CREATE TABLE IF NOT EXISTS client_operation_log (
  operation_id TEXT PRIMARY KEY,
  workout_id TEXT NOT NULL,
  operation_type TEXT NOT NULL,
  received_at TEXT NOT NULL,
  applied_at TEXT NULL,
  status TEXT NOT NULL,
  error_message TEXT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY (workout_id) REFERENCES workouts(id)
);
```

**File:** app/finalize_service.py (L25-40)
```python
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    validate_uuid(workout_id, "workout_id")
    prior = connection.execute(
        """
        SELECT status, error_message
        FROM client_operation_log
        WHERE operation_id = ?
        """,
        (operation_id,),
    ).fetchone()
    if prior:
        if prior["status"] == "applied":
            from .workout_service import get_workout_payload

            return FinalizeResult(HTTPStatus.OK, get_workout_payload(connection, workout_id))
        raise ValueError(prior["error_message"] or "operation previously rejected")
```

**File:** app/static/dashboard.js (L1-29)
```javascript
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
```

**File:** app/static/dashboard.js (L216-225)
```javascript
function renderResumeCard(draft) {
  const card = document.getElementById("resume-card");
  if (!card || !draft) {
    return;
  }
  card.innerHTML = `
    <p>Local draft: ${draft.workout_type.replaceAll("_", " ")} started ${draft.started_at}</p>
    <a href="/workouts/${draft.workout_id}">Resume current draft</a>
  `;
}
```

**File:** app/static/workout.js (L90-142)
```javascript
async function refreshWorkout() {
  const draft = await window.workoutDraftStorage.loadDraft(currentWorkoutId());
  if (draft) {
    document.getElementById("workout-title").textContent = `${formatWorkoutType(draft.workout_type)} Workout`;
    const list = document.getElementById("set-list");
    if (list) {
      list.innerHTML = draft.set_rows.length
        ? draft.set_rows
            .slice()
            .sort((left, right) => left.sequence_index - right.sequence_index)
            .map(setListItemHtml)
            .join("")
        : '<div class="list-item"><p>No sets logged yet.</p></div>';
    }
    const shell = document.getElementById("workout-shell");
    if (shell) {
      shell.innerHTML = `
        <div class="workout-shell-grid">
          <div class="shell-tile">
            <strong>Type</strong>
            <span>${formatWorkoutType(draft.workout_type)}</span>
          </div>
          <div class="shell-tile">
            <strong>Status</strong>
            <span>${formatWorkoutType(draft.status)}</span>
          </div>
          <div class="shell-tile">
            <strong>Started</strong>
            <span>${draft.started_at}</span>
          </div>
          <div class="shell-tile">
            <strong>Writes pending</strong>
            <span>${draft.pending_operation_ids.length}</span>
          </div>
        </div>
      `;
    }
    return;
  }
  const workoutId = currentWorkoutId();
  const response = await fetch(`/api/workouts/${workoutId}`);
  if (response.ok) {
    const workout = await response.json();
    window.__workoutPage.serverWorkout = workout;
    document.getElementById("workout-title").textContent = `${formatWorkoutType(workout.type)} Workout`;
    const list = document.getElementById("set-list");
    if (list) {
      list.innerHTML = workout.sets.length
        ? workout.sets.map(setListItemHtml).join("")
        : '<div class="list-item"><p>No sets logged yet.</p></div>';
    }
  }
}
```

**File:** app/static/summary.js (L15-29)
```javascript
  const draft = await window.workoutDraftStorage.loadDraft(workoutId);
  if (draft) {
    draft.status = "finalized-pending-sync";
    draft.last_local_write_at = operation.client_timestamp;
    draft.pending_operation_ids = [...draft.pending_operation_ids, operation.operation_id];
    await window.workoutDraftStorage.upsertDraftOnly(draft);
  }
  await window.workoutDraftStorage.queueOperation(operation);
  const success = await window.workoutDraftStorage.flushQueuedOperations();
  document.getElementById("finalize-status").textContent = success
    ? "Workout finalized and synced."
    : "Workout finalized locally and pending sync.";
  if (success) {
    await window.workoutDraftStorage.removeDraft(workoutId);
  }
```

# Corrections

The plan is architecturally sound and the core premise is correct. Here is a detailed critical review organized by severity.

---

## Confirmed Correct

- All four direct REST endpoints exist and are functional. [1](#0-0) 
- `client_operation_log` is used for idempotency by all three mutation services (`upsert_set`, `delete_set`, `finalize_workout`) and must be kept. [2](#0-1) 
- `queue_service.py` is only called from `post_client_operations` and can be deleted cleanly. [3](#0-2) 
- The `finalize_workout` endpoint already accepts `operation_id` and checks `_prior_operation` — Phase 1.2 requires no changes. [4](#0-3) 
- The DB version bump and migration logic in Phase 2.1 is correct. [5](#0-4) 

---

## Bugs

### 1. The 409 comment in `drainOfflineQueue` is factually wrong

The plan says `// 409 = already applied (idempotency), safe to remove`. This is incorrect. The idempotency path on set endpoints returns **200 OK**, not 409. A 409 from `PUT /api/workouts/<id>/sets/<set_id>` means `PermissionError("finalized workouts reject set mutations")`. [6](#0-5) [7](#0-6) 

The *behavior* (remove the entry) is still reasonable, but the comment will mislead anyone reading the code. Fix the comment to say "409 = workout is finalized, operation cannot be applied".

### 2. Timer interval is dropped

The current page initialization ends with:
```js
void loadWorkoutShell().then(refreshWorkout).then(renderTimer);
window.setInterval(() => { void renderTimer(); }, 1000);
``` [8](#0-7) 

The plan's `initWorkoutPage` calls `renderTimer()` once but never sets up the `setInterval`. The rest timer will display a static value and never count down.

### 3. Set-list click handler is not updated

The current click handler reads from `draft?.set_rows` and `window.__workoutPage.serverWorkout?.sets` to populate the edit form. [9](#0-8) 

Phase 3 never addresses this handler. After the rewrite, `window.__workoutPage.serverWorkout` will no longer be populated and `draft` will not exist, so clicking a set row to edit it will silently do nothing. The handler must be updated to read from `_workoutState.sets`.

### 4. `startWorkout` drops the IndexedDB unavailability alert

The current `startWorkout` has a catch block that shows a specific alert explaining that LAN IP access may block IndexedDB. [10](#0-9) 

The plan's replacement swallows the error from `pushOfflineRequest` silently. If IndexedDB is unavailable, the user navigates to a workout page that will show "Workout pending sync" indefinitely with no explanation.

### 5. `drainOfflineQueue` does not refresh the workout page UI

After draining queued operations on the workout page, `_workoutState` is stale — it still reflects the optimistic in-memory state from before the offline session. The plan does not call `confirmFromServer` or re-fetch `GET /api/workouts/<id>` after a successful drain. Sets that were queued and then synced will show optimistic data (missing server-assigned `created_at`, `updated_at`, etc.) until the user manually reloads.

---

## Gaps

### 6. HTML templates are not mentioned

The plan removes `renderResumeCard` and adds an `offline-queue-indicator` element, but never mentions updating the dashboard HTML template to remove `#resume-card` and add `#offline-queue-indicator`. [11](#0-10) 

### 7. Test migration is incomplete

The plan says to delete `test_queue_and_finalize.py`. But that file contains tests for behaviors that still exist after the refactor: exercise dictionary idempotency, finalize blocking set writes, and duplicate operation rejection. [12](#0-11) 

These tests should be **migrated** to use the direct endpoints (`POST /api/workouts/draft`, `PUT .../sets/...`, `POST .../finalize`), not deleted. The test for `process_operation_batch` directly (`test_queue_batch_ordering_helper`) is the only one that should be deleted outright. [13](#0-12) 

### 8. `window.__workoutPage.serverWorkout` references are not fully enumerated

Phase 3 introduces `_workoutState` but `window.__workoutPage.serverWorkout` is referenced in `mutateLocalDraft` (which is being deleted) and in the set-list click handler (bug #3 above). The plan should explicitly list every reference to `window.__workoutPage.serverWorkout` that needs to be removed or replaced.

### 9. `offline_queue` ordering relies on `created_at` string comparison

`listOfflineQueue` uses `index("by_created_at").getAll()`. If two operations are queued within the same millisecond (e.g., rapid taps), their relative order is undefined. Since the `id` is an auto-increment integer, ordering by `id` would be strictly correct. This is a minor concern but worth noting for a queue where ordering matters.

---

## Minor Observations

- The plan's `upsertSet` success path uses `applyOptimisticUpdate` to merge `payload.set` rather than calling `confirmFromServer` with the full workout response. This means `workout.updated_at` and other top-level fields won't be refreshed after a successful write. Not a functional bug, but inconsistent with the stated "server is source of truth" model.
- The `create_draft` endpoint returns `HTTPStatus.CONFLICT` (409) when a prior operation was rejected (not just when the workout already exists). The plan's `startWorkout` treats 409 as safe to ignore, which would silently navigate to a non-existent workout in this edge case. In practice this is nearly impossible with UUID workout IDs, but the comment should acknowledge it. [14](#0-13)

### Citations

**File:** app/routes_workouts.py (L33-65)
```python
@workouts_bp.post("/api/workouts/draft")
def post_workout_draft():
    payload = request.get_json(silent=True) or {}
    try:
        result = create_draft(get_db(), payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code


@workouts_bp.get("/api/workouts/<workout_id>")
def get_workout(workout_id: str):
    try:
        payload = get_workout_payload(get_db(), workout_id)
    except LookupError:
        return jsonify({"error": "workout not found"}), HTTPStatus.NOT_FOUND
    return jsonify(payload)


@workouts_bp.post("/api/workouts/<workout_id>/finalize")
def post_finalize(workout_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = finalize_workout(get_db(), workout_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code
```

**File:** app/routes_workouts.py (L68-79)
```python
@workouts_bp.post("/api/client-operations")
def post_client_operations():
    payload = request.get_json(silent=True) or {}
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return jsonify({"error": "operations must be a list"}), HTTPStatus.BAD_REQUEST
    try:
        acks = process_operation_batch(get_db(), operations)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify({"acks": acks})

```

**File:** app/routes_workouts.py (L161-172)
```python
@workouts_bp.put("/api/workouts/<workout_id>/sets/<set_id>")
def put_set(workout_id: str, set_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = upsert_set(get_db(), workout_id, set_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code
```

**File:** app/set_service.py (L197-203)
```python
def _load_mutable_workout(connection: sqlite3.Connection, workout_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT id, status FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if row is None:
        raise LookupError("workout not found")
    if row["status"] != "draft":
        raise PermissionError("finalized workouts reject set mutations")
    return row
```

**File:** app/set_service.py (L234-238)
```python
def _prior_operation(connection: sqlite3.Connection, operation_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT status, error_message FROM client_operation_log WHERE operation_id = ?",
        (operation_id,),
    ).fetchone()
```

**File:** app/finalize_service.py (L25-40)
```python
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    validate_uuid(workout_id, "workout_id")
    prior = connection.execute(
        """
        SELECT status, error_message
        FROM client_operation_log
        WHERE operation_id = ?
        """,
        (operation_id,),
    ).fetchone()
    if prior:
        if prior["status"] == "applied":
            from .workout_service import get_workout_payload

            return FinalizeResult(HTTPStatus.OK, get_workout_payload(connection, workout_id))
        raise ValueError(prior["error_message"] or "operation previously rejected")
```

**File:** app/static/dashboard.js (L1-29)
```javascript
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
```

**File:** app/static/dashboard.js (L216-225)
```javascript
function renderResumeCard(draft) {
  const card = document.getElementById("resume-card");
  if (!card || !draft) {
    return;
  }
  card.innerHTML = `
    <p>Local draft: ${draft.workout_type.replaceAll("_", " ")} started ${draft.started_at}</p>
    <a href="/workouts/${draft.workout_id}">Resume current draft</a>
  `;
}
```

**File:** app/static/dashboard.js (L539-544)
```javascript
  } catch (error) {
    console.error("Start workout failed:", error);
    window.alert(
      "Could not start a workout. The site needs IndexedDB (site data) enabled. If you opened this app via a LAN IP (not localhost), your browser may block storage; try http://127.0.0.1 or http://localhost instead.",
    );
  }
```

**File:** app/static/workout.js (L320-342)
```javascript
document.getElementById("set-list")?.addEventListener("click", (event) => {
  const target = event.target.closest(".set-row");
  if (!target) {
    return;
  }
  const setId = target.dataset.setId;
  void (async () => {
    const draft = await window.workoutDraftStorage.loadDraft(currentWorkoutId());
    const localSelected = draft?.set_rows?.find((item) => item.id === setId);
    const workout = window.__workoutPage.serverWorkout;
    const selected = localSelected || workout?.sets?.find((item) => item.id === setId);
    if (!selected) {
      return;
    }
    document.getElementById("set-id").value = selected.id;
    document.getElementById("exercise-name").value = selected.exercise_name;
    document.getElementById("sequence-index").value = selected.sequence_index;
    document.getElementById("set-type").value = selected.set_type;
    document.getElementById("weight-kg").value = selected.weight_kg ?? "";
    document.getElementById("reps").value = selected.reps ?? "";
    document.getElementById("duration-seconds").value = selected.duration_seconds ?? "";
  })();
});
```

**File:** app/static/workout.js (L348-351)
```javascript
void loadWorkoutShell().then(refreshWorkout).then(renderTimer);
window.setInterval(() => {
  void renderTimer();
}, 1000);
```

**File:** tests/test_queue_and_finalize.py (L168-213)
```python
def test_finalize_updates_exercise_dictionary_exactly_once(client, app):
    workout_id = "b6c1f531-f7ef-47b3-8819-4cf0d6763f04"
    operations = [
        {
            "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
            "workout_id": workout_id,
            "operation_type": "create_draft",
            "client_timestamp": "2026-03-29T10:00:00Z",
            "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
        },
        {
            "operation_id": "f1e7768f-dff6-4745-a69f-d0a47c6d8c0f",
            "workout_id": workout_id,
            "operation_type": "upsert_set",
            "client_timestamp": "2026-03-29T10:05:00Z",
            "payload": {
                "set_id": "ac64498d-d6f8-451e-a914-fd44f65f4ec6",
                "exercise_name": "Bench Press",
                "sequence_index": 0,
                "weight_kg": 80,
                "reps": 5,
                "duration_seconds": None,
                "set_type": "normal",
            },
        },
        {
            "operation_id": "67ea81dd-0c20-4c1b-a639-da281e6148f2",
            "workout_id": workout_id,
            "operation_type": "finalize_workout",
            "client_timestamp": "2026-03-29T10:30:00Z",
            "payload": {
                "ended_at": "2026-03-29T10:30:00Z",
                "feeling_score": 4,
                "notes": "done",
            },
        },
    ]
    client.post("/api/client-operations", json={"operations": operations})
    client.post("/api/client-operations", json={"operations": [operations[-1]]})
    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT usage_count FROM exercise_dictionary WHERE name = 'Bench Press'"
        ).fetchone()
    assert row["usage_count"] == 1
```

**File:** tests/test_queue_and_finalize.py (L216-232)
```python
def test_queue_batch_ordering_helper(app):
    with app.app_context():
        from app.db import get_db

        acks = process_operation_batch(
            get_db(),
            [
                {
                    "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
                    "workout_id": "b6c1f531-f7ef-47b3-8819-4cf0d6763f04",
                    "operation_type": "create_draft",
                    "client_timestamp": "2026-03-29T10:00:00Z",
                    "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
                }
            ],
        )
    assert acks[0]["status"] == "applied"
```

**File:** app/workout_service.py (L36-43)
```python
    if prior:
        workout = get_workout_payload(connection, workout_id)
        if prior["status"] == "applied":
            return OperationResult(HTTPStatus.OK, workout)
        return OperationResult(
            HTTPStatus.CONFLICT,
            {"error": prior["error_message"] or "operation previously rejected"},
        )
```

