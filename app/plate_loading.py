from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlateSolution:
    achieved_weight: float
    per_side: list[float]


def calculate_plate_loading(
    *,
    target_weight: float,
    barbell_weight: float,
    inventory: list[dict[str, float | int]],
    search_radius: float = 20.0,
) -> dict[str, object]:
    target_side = (target_weight - barbell_weight) / 2
    if target_side < 0:
        raise ValueError("target weight must be at least the barbell weight")
    solutions = _enumerate_solutions(
        inventory,
        barbell_weight=barbell_weight,
        max_side_weight=target_side + (search_radius / 2),
    )
    exact = [solution for solution in solutions if _same(solution.achieved_weight, target_weight)]
    exact_solution = _pick_best(exact)
    lower = [solution for solution in solutions if solution.achieved_weight < target_weight]
    higher = [solution for solution in solutions if solution.achieved_weight > target_weight]
    return {
        "target_weight": target_weight,
        "barbell_weight": barbell_weight,
        "exact_match": _serialize_solution(exact_solution),
        "nearest_lower": _serialize_solution(_pick_nearest(lower, target_weight, reverse=True)),
        "nearest_higher": _serialize_solution(_pick_nearest(higher, target_weight, reverse=False)),
    }


def _enumerate_solutions(
    inventory: list[dict[str, float | int]],
    *,
    barbell_weight: float,
    max_side_weight: float,
) -> list[PlateSolution]:
    rows = sorted(
        [
            (float(row["weight_kg"]), int(row["plate_count"]) // 2)
            for row in inventory
            if int(row["plate_count"]) > 0
        ],
        reverse=True,
    )
    solutions: list[PlateSolution] = []

    def search(index: int, current: list[float], side_weight: float) -> None:
        if side_weight <= max_side_weight + 1e-9:
            achieved = round(barbell_weight + (side_weight * 2), 2)
            solutions.append(PlateSolution(achieved_weight=achieved, per_side=current.copy()))
        if index >= len(rows):
            return
        plate_weight, available_per_side = rows[index]
        for count in range(available_per_side + 1):
            current.extend([plate_weight] * count)
            search(index + 1, current, side_weight + (plate_weight * count))
            for _ in range(count):
                current.pop()

    search(0, [], 0)
    deduped: dict[tuple[float, tuple[float, ...]], PlateSolution] = {}
    for solution in solutions:
        total = round(solution.achieved_weight, 2)
        key = (total, tuple(solution.per_side))
        deduped[key] = PlateSolution(total, sorted(solution.per_side, reverse=True))
    return [
        PlateSolution(achieved_weight=round(item.achieved_weight + 0, 2), per_side=item.per_side)
        for item in deduped.values()
    ]


def _pick_best(solutions: list[PlateSolution]) -> PlateSolution | None:
    if not solutions:
        return None
    return sorted(solutions, key=lambda item: (len(item.per_side), item.per_side))[0]


def _pick_nearest(
    solutions: list[PlateSolution],
    target_weight: float,
    *,
    reverse: bool,
) -> PlateSolution | None:
    if not solutions:
        return None
    return sorted(
        solutions,
        key=lambda item: (abs(item.achieved_weight - target_weight), len(item.per_side), item.achieved_weight),
        reverse=False,
    )[0]


def _serialize_solution(solution: PlateSolution | None) -> dict[str, object] | None:
    if solution is None:
        return None
    return {
        "achieved_weight": round(solution.achieved_weight, 2),
        "per_side": solution.per_side,
        "plate_count": len(solution.per_side) * 2,
    }


def _same(left: float, right: float) -> bool:
    return abs(left - right) < 1e-6
