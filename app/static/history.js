const historyList = document.getElementById("history-list");
const emptyStateId = "history-empty-state";
const modalShell = document.getElementById("history-delete-modal");
const modalCopy = document.getElementById("history-delete-copy");
const modalError = document.getElementById("history-delete-error");
const confirmButton = document.getElementById("history-delete-confirm");
const cancelButton = document.getElementById("history-delete-cancel");

let activeWorkoutId = null;
let lastTrigger = null;

function setModalOpen(isOpen) {
  if (!modalShell) {
    return;
  }
  modalShell.classList.toggle("hidden", !isOpen);
  modalShell.setAttribute("aria-hidden", String(!isOpen));
  document.body.classList.toggle("modal-open", isOpen);
  if (isOpen) {
    confirmButton?.focus();
  } else {
    activeWorkoutId = null;
    modalError?.classList.add("hidden");
    modalError.textContent = "";
    confirmButton?.classList.remove("is-loading");
    confirmButton?.removeAttribute("disabled");
    cancelButton?.removeAttribute("disabled");
    lastTrigger?.focus();
  }
}

function ensureEmptyState() {
  if (!historyList || historyList.querySelector("[data-workout-id]")) {
    return;
  }
  if (document.getElementById(emptyStateId)) {
    return;
  }
  const section = document.createElement("section");
  section.className = "card history-empty-state";
  section.id = emptyStateId;
  section.innerHTML = '<p class="page-copy">No finalized workouts yet.</p>';
  historyList.append(section);
}

function openDeleteModal(button) {
  activeWorkoutId = button.dataset.deleteWorkout || null;
  lastTrigger = button;
  modalError?.classList.add("hidden");
  modalError.textContent = "";
  const workoutCard = button.closest("[data-workout-id]");
  const label = workoutCard?.dataset.workoutLabel || "this workout";
  if (modalCopy) {
    modalCopy.textContent = `Delete ${label}? This cannot be undone.`;
  }
  setModalOpen(true);
}

async function confirmDelete() {
  if (!activeWorkoutId || !confirmButton || !cancelButton) {
    return;
  }
  confirmButton.classList.add("is-loading");
  confirmButton.setAttribute("disabled", "disabled");
  cancelButton.setAttribute("disabled", "disabled");
  try {
    const response = await fetch(`/api/workouts/${activeWorkoutId}`, {
      method: "DELETE",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "Unable to delete workout");
    }
    historyList?.querySelector(`[data-workout-id="${activeWorkoutId}"]`)?.remove();
    setModalOpen(false);
    ensureEmptyState();
  } catch (error) {
    modalError.textContent = error.message || "Unable to delete workout";
    modalError.classList.remove("hidden");
    confirmButton.classList.remove("is-loading");
    confirmButton.removeAttribute("disabled");
    cancelButton.removeAttribute("disabled");
  }
}

historyList?.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete-workout]");
  if (!deleteButton) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  openDeleteModal(deleteButton);
});

confirmButton?.addEventListener("click", () => {
  void confirmDelete();
});

cancelButton?.addEventListener("click", () => {
  setModalOpen(false);
});

modalShell?.addEventListener("click", (event) => {
  if (event.target instanceof HTMLElement && event.target.hasAttribute("data-close-modal")) {
    setModalOpen(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && modalShell && !modalShell.classList.contains("hidden")) {
    setModalOpen(false);
  }
});
