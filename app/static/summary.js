async function finalizeWorkout(event) {
  event.preventDefault();
  const workoutId = window.__summaryPage.workoutId;
  const operation = {
    operation_id: newUuid(),
    workout_id: workoutId,
    operation_type: "finalize_workout",
    client_timestamp: new Date().toISOString(),
    payload: {
      ended_at: new Date().toISOString(),
      feeling_score: Number(document.getElementById("feeling-score").value),
      notes: document.getElementById("workout-notes").value || null,
    },
  };
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
}

document.getElementById("finalize-form")?.addEventListener("submit", (event) => {
  void finalizeWorkout(event);
});
