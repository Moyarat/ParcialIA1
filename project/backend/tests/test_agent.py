"""Validation tests for the real Emergency Control agent."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agent import State, _initial, _make_state, solve  # noqa: E402
from simulator import goal_satisfied, load_scenario, simulate  # noqa: E402


def test_agent_plan_is_legal_and_reaches_goal() -> None:
    scenario = load_scenario()
    plan = solve(scenario)
    assert plan["solution_found"] is True
    assert plan["steps"]
    assert plan["total_cost"] == sum(step["cost"] for step in plan["steps"])

    final = simulate(scenario, plan["steps"])
    assert goal_satisfied(scenario, final)
    assert final["energy_spent"] == plan["total_cost"]
    assert {step["op"] for step in plan["steps"]} <= {
        "MOVE",
        "PICKUP",
        "DROP",
        "INTERACT",
    }


def test_equivalent_states_have_same_canonical_representation() -> None:
    scenario = load_scenario()
    initial = _initial(scenario)
    first = _make_state(
        initial,
        payload=("KEY2", "KEY1"),
        ground=(("KEY2", "Z2"), ("KEY1", "Z1")),
    )
    second = _make_state(
        initial,
        payload=("KEY1", "KEY2"),
        ground=(("KEY1", "Z1"), ("KEY2", "Z2")),
    )
    assert first == second
    assert hash(first) == hash(second)


def test_relevant_information_keeps_states_distinct() -> None:
    scenario = load_scenario()
    initial = _initial(scenario)
    lower_battery = _make_state(initial, battery=initial.battery - 1)
    different_position = _make_state(initial, zone="Z4")
    different_environment = _make_state(
        initial,
        doors={**dict(initial.doors), "DOOR1": "OPEN"},
    )
    assert lower_battery != initial
    assert different_position != initial
    assert different_environment != initial


def test_unsolvable_mission_returns_failure() -> None:
    scenario = {
        "robot": {"start": "Z1", "battery_max": 10, "battery_start": 10, "cargo_capacity": 1},
        "zones": [{"id": "Z1", "recharge": False}],
        "corridors": [],
        "doors": [],
        "keys": [],
        "tools": [],
        "materials": [],
        "panels": [],
        "stations": [
            {
                "id": "STATION",
                "zone": "Z1",
                "state": "OFFLINE",
                "requires": {"panels_ok": ["MISSING_PANEL"]},
            }
        ],
        "chargers": [],
        "goal": {"stations_online": ["STATION"]},
        "action_costs": {"pickup": 1, "drop": 1, "interact": 1, "recharge": 1},
    }
    result = solve(scenario)
    assert result["solution_found"] is False
    assert result["steps"] == []


def test_scenario_contains_alternative_routes_with_different_costs() -> None:
    scenario = load_scenario()
    routes = {
        (corridor["from"], corridor["to"]): corridor["cost"]
        for corridor in scenario["corridors"]
    }
    assert routes[("Z1", "Z4")] != routes[("Z1", "Z2")]
    assert routes[("Z2", "Z5")] > routes[("Z4", "Z5")]


def test_cost_is_taken_from_scenario() -> None:
    scenario = load_scenario()
    plan = solve(scenario)
    assert plan["total_cost"] == sum(step["cost"] for step in plan["steps"])
    assert all(step["cost"] >= 0 for step in plan["steps"])


if __name__ == "__main__":
    test_agent_plan_is_legal_and_reaches_goal()
    test_equivalent_states_have_same_canonical_representation()
    test_relevant_information_keeps_states_distinct()
    test_unsolvable_mission_returns_failure()
    test_scenario_contains_alternative_routes_with_different_costs()
    test_cost_is_taken_from_scenario()
    print("All agent validation tests passed.")
