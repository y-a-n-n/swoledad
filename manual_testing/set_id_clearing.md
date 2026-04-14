# Manual Testing: Set-ID Clearing Fix

## Bug Description

After saving a set, the hidden `set-id` input was never cleared. When filling in a second set and hitting "Save Set", the stale ID from the previous save was reused instead of generating a new UUID — causing every subsequent save to overwrite the first set rather than create a new one.

## Expected Behavior

Each "Save Set" submission should create a new set entry. After saving, the form should be cleared so the next set gets a fresh UUID.

## Test Steps

### 1. Start a New Workout

- Navigate to the dashboard
- Select a workout type (e.g., "Strength")
- Click "Start Workout"

### 2. Add First Set

- Enter an exercise name (e.g., "Squat")
- Enter a weight (e.g., "100")
- Enter reps (e.g., "5")
- Click "Save Set"

**Expected:** The set appears in the workout log below the form.

### 3. Add Second Set

- Enter a different exercise name (e.g., "Bench Press")
- Enter a different weight (e.g., "80")
- Enter different reps (e.g., "8")
- Click "Save Set"

**Expected:** 
- The second set appears in the log
- Both sets are visible simultaneously
- The first set (Squat) is NOT replaced by the second set (Bench Press)

### 4. Add Third Set

- Enter another exercise (e.g., "Deadlift")
- Enter weight (e.g., "140")
- Enter reps (e.g., "3")
- Click "Save Set"

**Expected:** All three sets appear in the log, each as separate entries.

### 5. Verify Form Clears

After saving any set, open the browser's developer console and run:

```javascript
document.getElementById('set-id').value
```

**Expected:** The value should be empty (`""`), not a UUID.

### 6. Verify Different UUIDs

Open the developer console and run after adding multiple sets:

```javascript
// Get all set rows
document.querySelectorAll('.set-row, [data-set-id], tr[data-id]').forEach(el => {
  console.log(el.dataset.id || el.dataset.setId);
});
```

Or inspect the DOM directly to confirm each set has a unique identifier.

## Test Matrix

| Set # | Exercise | Weight | Reps | Expected Result |
|-------|----------|--------|------|-----------------|
| 1     | Squat    | 100    | 5    | Set created     |
| 2     | Bench Press | 80  | 8    | New set created (2 total) |
| 3     | Deadlift | 140    | 3    | New set created (3 total) |

## Failure Modes

If the bug is present:
- Only the last set will appear in the log
- Previous sets are overwritten
- The `set-id` input retains the previous UUID after saving

## Automated E2E Test

Run the deterministic end-to-end test:

```bash
cd manual_testing
python test_set_id_clearing.py
```

This script:
1. Creates a temporary directory with a unique database
2. Starts the Flask app on port 5001
3. Uses rodney to automate the browser and add 3 sets
4. Verifies the `set-id` is cleared after each save
5. Verifies all 3 sets appear in the DOM
6. Tears down the server and cleans up the temp directory

For manual rodney testing:

```bash
rodney start
rodney open http://localhost:5000
rodney click "#start-workout-form button"
rodney input "#exercise-name" "Squat"
rodney input "#weight-kg" "100"
rodney input "#reps" "5"
rodney click "#set-form button[type=submit]"
rodney sleep 1
rodney js "document.getElementById('set-id').value"
rodney stop
```
