# Fix rejected finalize silently deletes local draft

*2026-04-19T12:26:13Z by Showboat 0.6.1*
<!-- showboat-id: f77da34f-262b-46cb-8ff7-501ac1c3a987 -->

```bash {image}
screenshots/rejected-finalize-dashboard.png
```

![1fa76d46-2026-04-19](1fa76d46-2026-04-19.png)

## Issue

When a finalize operation is rejected by the server (e.g., invalid feeling_score=0), the local draft was incorrectly deleted because `reconcileDraftFromServer` treated both 'applied' and 'rejected' as resolved operations. This left users unable to resume or retry their draft.

## Fix

Modified `flushQueuedOperations` and `reconcileDraftFromServer` to track rejected operations separately. The draft is now only deleted when there are applied operations with no remaining pending operations - not when operations are rejected.
