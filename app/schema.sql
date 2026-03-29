CREATE TABLE IF NOT EXISTS workouts (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('strength', 'cross_training', 'imported_cardio')),
  status TEXT NOT NULL CHECK (status IN ('draft', 'finalized', 'archived')),
  started_at TEXT NOT NULL,
  ended_at TEXT NULL,
  feeling_score INTEGER NULL,
  notes TEXT NULL,
  source TEXT NOT NULL CHECK (source IN ('manual', 'external_import')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workout_sets (
  id TEXT PRIMARY KEY,
  workout_id TEXT NOT NULL,
  exercise_name TEXT NOT NULL,
  sequence_index INTEGER NOT NULL,
  weight_kg REAL NULL,
  reps INTEGER NULL,
  duration_seconds INTEGER NULL,
  set_type TEXT NOT NULL CHECK (set_type IN ('normal', 'amrap', 'for_time')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workout_sets_workout_sequence
  ON workout_sets (workout_id, sequence_index);
CREATE INDEX IF NOT EXISTS idx_workout_sets_workout_id
  ON workout_sets (workout_id);

CREATE TABLE IF NOT EXISTS exercise_dictionary (
  name TEXT PRIMARY KEY,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  usage_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS plate_inventory (
  weight_kg REAL PRIMARY KEY,
  plate_count INTEGER NOT NULL CHECK (plate_count >= 0)
);

CREATE TABLE IF NOT EXISTS user_config (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_activities (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('garmin')),
  provider_activity_id TEXT NOT NULL,
  activity_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('discovered', 'pending_review', 'linked', 'dismissed')),
  started_at TEXT NOT NULL,
  ended_at TEXT NULL,
  duration_seconds INTEGER NULL,
  distance_meters REAL NULL,
  calories INTEGER NULL,
  avg_heart_rate INTEGER NULL,
  max_heart_rate INTEGER NULL,
  elevation_gain_meters REAL NULL,
  raw_payload_json TEXT NOT NULL,
  linked_workout_id TEXT NULL,
  dismissed_at TEXT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (linked_workout_id) REFERENCES workouts(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_provider_activity
  ON external_activities (provider, provider_activity_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_external_linked_workout
  ON external_activities (linked_workout_id)
  WHERE linked_workout_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_external_status_started
  ON external_activities (status, started_at);
CREATE INDEX IF NOT EXISTS idx_external_linked_lookup
  ON external_activities (linked_workout_id);

CREATE TABLE IF NOT EXISTS sync_checkpoints (
  provider TEXT PRIMARY KEY,
  last_successful_sync_at TEXT NULL,
  last_attempted_sync_at TEXT NULL,
  last_status TEXT NULL,
  last_error TEXT NULL,
  updated_at TEXT NOT NULL
);

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
