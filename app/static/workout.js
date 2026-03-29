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

void loadWorkoutShell();
