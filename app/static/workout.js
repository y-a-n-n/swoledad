async function loadWorkoutShell() {
  const shell = document.getElementById("workout-shell");
  if (!shell || !window.__workoutPage) {
    return;
  }
  const { workoutId, serverWorkout } = window.__workoutPage;
  let localDraft = null;
  try {
    const drafts = await window.workoutDraftStorage.listLocalDrafts();
    localDraft = drafts.find((item) => item.workout_id === workoutId) || null;
  } catch (_error) {
    localDraft = null;
  }

  if (localDraft) {
    document.getElementById("workout-title").textContent = `${localDraft.workout_type} workout`;
    shell.innerHTML = `
      <p>Workout ID: ${localDraft.workout_id}</p>
      <p>Status: ${localDraft.status}</p>
      <p>Started: ${localDraft.started_at}</p>
      <p>Saved locally and ready for logging.</p>
    `;
    return;
  }

  if (serverWorkout) {
    document.getElementById("workout-title").textContent = `${serverWorkout.type} workout`;
    shell.innerHTML = `
      <p>Workout ID: ${serverWorkout.id}</p>
      <p>Status: ${serverWorkout.status}</p>
      <p>Started: ${serverWorkout.started_at}</p>
      <p>Loaded from the server.</p>
    `;
    return;
  }

  shell.innerHTML = "<p>No local or server draft was found for this workout.</p>";
}

const TIMER_KEY_PREFIX = "workout-timer:";

function currentWorkoutId() {
  return window.__workoutPage?.workoutId;
}

function setListItemHtml(item) {
  return `
    <button type="button" class="set-row" data-set-id="${item.id}">
      ${item.sequence_index + 1}. ${item.exercise_name} - ${item.weight_kg ?? "bodyweight"} x ${item.reps ?? item.duration_seconds}
    </button>
  `;
}

async function refreshWorkout() {
  const workoutId = currentWorkoutId();
  const response = await fetch(`/api/workouts/${workoutId}`);
  if (!response.ok) {
    return;
  }
  const workout = await response.json();
  window.__workoutPage.serverWorkout = workout;
  const list = document.getElementById("set-list");
  if (list) {
    list.innerHTML = workout.sets.length
      ? workout.sets.map(setListItemHtml).join("")
      : "<p>No sets logged yet.</p>";
  }
}

async function upsertSet(event) {
  event.preventDefault();
  const workoutId = currentWorkoutId();
  const setId = document.getElementById("set-id").value || crypto.randomUUID();
  document.getElementById("set-id").value = setId;
  const payload = {
    operation_id: crypto.randomUUID(),
    operation_type: "upsert_set",
    client_timestamp: new Date().toISOString(),
    exercise_name: document.getElementById("exercise-name").value,
    sequence_index: Number(document.getElementById("sequence-index").value),
    weight_kg: document.getElementById("weight-kg").value ? Number(document.getElementById("weight-kg").value) : null,
    reps: document.getElementById("reps").value ? Number(document.getElementById("reps").value) : null,
    duration_seconds: document.getElementById("duration-seconds").value ? Number(document.getElementById("duration-seconds").value) : null,
    set_type: document.getElementById("set-type").value,
  };
  const response = await fetch(`/api/workouts/${workoutId}/sets/${setId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    return;
  }
  await refreshWorkout();
}

async function deleteSelectedSet() {
  const workoutId = currentWorkoutId();
  const setId = document.getElementById("set-id").value;
  if (!setId) {
    return;
  }
  const response = await fetch(`/api/workouts/${workoutId}/sets/${setId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      operation_id: crypto.randomUUID(),
      operation_type: "delete_set",
      client_timestamp: new Date().toISOString(),
    }),
  });
  if (!response.ok) {
    return;
  }
  document.getElementById("set-form").reset();
  document.getElementById("set-id").value = "";
  await refreshWorkout();
}

async function loadSuggestions() {
  const exerciseName = document.getElementById("exercise-name").value;
  const response = await fetch(`/api/exercises/suggestions?query=${encodeURIComponent(exerciseName)}`);
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  const datalist = document.getElementById("exercise-suggestions");
  datalist.innerHTML = payload.items
    .map((item) => `<option value="${item.exercise_name}">${item.reason}</option>`)
    .join("");
}

async function applyPrefill(liftKey) {
  const response = await fetch(`/api/big3/prefill/${liftKey}`);
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  document.getElementById("exercise-name").value = payload.exercise_name;
  document.getElementById("weight-kg").value = payload.weight_kg ?? "";
  document.getElementById("reps").value = payload.reps ?? "";
  await updatePlateLoading();
}

async function updatePlateLoading() {
  const weight = document.getElementById("weight-kg").value;
  const container = document.getElementById("plate-loading");
  if (!weight) {
    container.textContent = "Enter a weight to see plate loading.";
    return;
  }
  const response = await fetch(`/api/plate-loading?target_weight=${encodeURIComponent(weight)}`);
  if (!response.ok) {
    container.textContent = "Unable to compute plate loading.";
    return;
  }
  const payload = await response.json();
  const exact = payload.exact_match;
  if (exact) {
    container.textContent = `Exact: ${exact.achieved_weight} kg using ${exact.per_side.join(", ") || "no plates"} per side.`;
    return;
  }
  container.textContent = `Nearest lower: ${payload.nearest_lower?.achieved_weight ?? "n/a"} kg. Nearest higher: ${payload.nearest_higher?.achieved_weight ?? "n/a"} kg.`;
}

function loadTimerState() {
  const raw = localStorage.getItem(`${TIMER_KEY_PREFIX}${currentWorkoutId()}`);
  return raw ? JSON.parse(raw) : null;
}

function saveTimerState(state) {
  localStorage.setItem(`${TIMER_KEY_PREFIX}${currentWorkoutId()}`, JSON.stringify(state));
}

function renderTimer() {
  const display = document.getElementById("timer-display");
  const state = loadTimerState();
  if (!state || state.mode !== "running") {
    display.textContent = "Timer idle.";
    return;
  }
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - Date.parse(state.started_at)) / 1000));
  const remaining = Math.max(0, state.target_duration_seconds - elapsedSeconds);
  display.textContent = `Rest timer: ${remaining}s remaining`;
}

function startTimer() {
  saveTimerState({
    mode: "running",
    started_at: new Date().toISOString(),
    stopped_at: null,
    target_duration_seconds: Number(document.getElementById("timer-target").value),
  });
  renderTimer();
}

function stopTimer() {
  saveTimerState({
    mode: "stopped",
    started_at: null,
    stopped_at: new Date().toISOString(),
    target_duration_seconds: Number(document.getElementById("timer-target").value),
  });
  renderTimer();
}

document.getElementById("set-form")?.addEventListener("submit", upsertSet);
document.getElementById("delete-set")?.addEventListener("click", deleteSelectedSet);
document.getElementById("exercise-name")?.addEventListener("input", loadSuggestions);
document.getElementById("weight-kg")?.addEventListener("input", updatePlateLoading);
document.querySelectorAll(".prefill-button").forEach((button) => {
  button.addEventListener("click", () => {
    void applyPrefill(button.dataset.lift);
  });
});
document.getElementById("start-timer")?.addEventListener("click", startTimer);
document.getElementById("stop-timer")?.addEventListener("click", stopTimer);
document.getElementById("set-list")?.addEventListener("click", (event) => {
  const target = event.target.closest(".set-row");
  if (!target) {
    return;
  }
  const setId = target.dataset.setId;
  const workout = window.__workoutPage.serverWorkout;
  const selected = workout?.sets?.find((item) => item.id === setId);
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
});

void loadWorkoutShell().then(refreshWorkout).then(renderTimer);
window.setInterval(renderTimer, 1000);
