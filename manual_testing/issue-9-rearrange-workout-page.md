# Issue 9: Rearrange workout page

## Setup

- Start the app locally with `FLASK_APP=app:create_app .venv/bin/flask run --host 0.0.0.0 --port 5000`.
- Create or open a draft workout.
- Open the active workout page for that draft.

## Original issue repro

1. Load the workout page.
2. Observe that `Session Status` appears near the top of the page before the set editor.
3. Observe that `Duration (seconds)` is always visible even when the set type is `normal`.
4. Observe that quick prefill lives in a separate accordion below the main form instead of next to the main set action.

## Verification after the fix

1. Load the workout page and confirm the main set editor appears before the session status card.
2. Confirm the quick prefill buttons sit directly above `Save Set`.
3. Confirm `Squat`, `Bench Press`, and `Deadlift` render as three evenly sized buttons on desktop widths.
4. Confirm the `Duration (seconds)` field is hidden when `Set type` is `normal`.
5. Change `Set type` to `amrap` and confirm the duration field appears.
6. Change `Set type` to `for_time` and confirm the duration field remains visible.
7. Change `Set type` back to `normal` and confirm the duration field hides again.
8. Scroll to the bottom portion of the workout page and confirm `Session Status` is below the logged sets and plate loading panels.

## Expected results

- The workout form is the primary focus at the top of the editing flow.
- Quick prefill is positioned immediately before the save action.
- The duration field is only shown for time-based set types.
- Session status is moved to the bottom of the page.
