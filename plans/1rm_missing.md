There are several workouts that don't show 1rm estimates in the history list. Debug why:

b73cb966-56e1-5b07-8e88-ca4f79e79b11
5d1a6e8e-f3d8-5f3e-9922-e2cd043bf9f4

I think this is because 

BIG3_NAMES = {
    "squat": "Squat",
    "bench_press": "Bench Press",
    "deadlift": "Deadlift",
}

and imported workouts have "squats".

Change all exercises in the db from "squats" -> "squat"
