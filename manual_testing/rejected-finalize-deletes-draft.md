# Manual Testing: Rejected Finalize Silently Deletes Draft

## Issue
When a finalize operation is rejected by the server (e.g., `feeling_score = 0`), the local draft is incorrectly deleted, leaving users unable to resume or retry.

## Reproduction Steps

1. Start a new strength workout
2. Add some exercise sets
3. Go to the summary page
4. Submit with `feeling_score = 0` (the server rejects this as invalid - must be 1-5)
5. Navigate back to the dashboard
6. Check if the "Resume current draft" card is still visible

## Expected Behavior (After Fix)
- The "Resume current draft" card should still be visible on the dashboard
- User should be able to click "Resume current draft" and retry with a valid feeling_score (1-5)

## Previous Behavior (Bug)
- The "Resume current draft" card disappears after a rejected finalize
- The workout is still a draft on the server, but the local draft is gone
- User loses ability to resume or retry

## Verification
1. After fix: Submit with invalid feeling_score, return to dashboard
2. Confirm "Resume current draft" card is still present
3. Resume the workout and submit with valid feeling_score (e.g., 3)
4. Confirm the draft is now properly deleted after successful finalize