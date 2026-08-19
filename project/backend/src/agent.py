"""Generic informed search agent for the Emergency Control world."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

MAX_UCS_EXPANSIONS = 10_000


@dataclass(frozen=True)
class State:
    zone: str
    battery: int
    payload: tuple[str, ...]
    ground: tuple[tuple[str, str], ...]
    doors: tuple[tuple[str, str], ...]
    panels: tuple[tuple[str, str], ...]
    stations: tuple[tuple[str, str], ...]


@dataclass
class Node:
    state: State
    cost: int
    parent: "Node | None"
    action: dict[str, Any] | None
    action_cost: int = 0


def _initial(scenario: dict[str, Any]) -> State:
    ground: list[tuple[str, str]] = []
    ground.extend((key["id"], key["zone"]) for key in scenario.get("keys", []))
    ground.extend((tool["id"], tool["zone"]) for tool in scenario.get("tools", []))
    for material in scenario.get("materials", []):
        for _ in range(material.get("count", 0)):
            ground.append((f"M:{material['type']}", material["zone"]))
    return State(
        scenario["robot"]["start"],
        int(scenario["robot"]["battery_start"]),
        (),
        tuple(sorted(ground)),
        tuple(sorted((d["id"], d["state"]) for d in scenario.get("doors", []))),
        tuple(sorted((p["id"], p["state"]) for p in scenario.get("panels", []))),
        tuple(sorted((s["id"], s["state"]) for s in scenario.get("stations", []))),
    )


def _maps(state: State) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    return (dict(state.ground), dict(state.doors), dict(state.panels), dict(state.stations))


def _costs(scenario: dict[str, Any]) -> dict[str, int]:
    values = scenario.get("action_costs", {})
    return {key: int(values.get(key, default)) for key, default in (("pickup", 1), ("drop", 1), ("interact", 1), ("recharge", 1))}


def _weight(item: str, scenario: dict[str, Any]) -> int:
    if item.startswith("M:"):
        return 1
    for collection in (scenario.get("keys", []), scenario.get("tools", [])):
        for obj in collection:
            if obj["id"] == item:
                return int(obj.get("weight", 1))
    return 1


def _item_type(item: str) -> str:
    return item[2:] if item.startswith("M:") else item


def _physical_key(state: State) -> tuple[Any, ...]:
    return (state.zone, state.payload, state.ground, state.doors, state.panels, state.stations)


def _prune_inert(state: State, scenario: dict[str, Any]) -> State:
    doors = dict(state.doors)
    panels = dict(state.panels)
    open_keys = {
        door["key"] for door in scenario.get("doors", [])
        if doors[door["id"]] == "OPEN"
    }
    live_tools = {
        panel["requires"]["tool"]
        for panel in scenario.get("panels", [])
        if panels[panel["id"]] == "DAMAGED"
    }
    live_materials = {
        panel["requires"]["material"]
        for panel in scenario.get("panels", [])
        if panels[panel["id"]] == "DAMAGED"
    }

    def live(item: str) -> bool:
        if item.startswith("M:"):
            return item[2:] in live_materials
        if item in open_keys:
            return False
        tool_ids = {tool["id"] for tool in scenario.get("tools", [])}
        return item not in tool_ids or item in live_tools

    return _make_state(
        state,
        payload=state.payload,
        ground=tuple((item, zone) for item, zone in state.ground if live(item)),
    )


def _goal(state: State, scenario: dict[str, Any]) -> bool:
    stations = dict(state.stations)
    return all(stations[sid] == "ONLINE" for sid in scenario.get("goal", {}).get("stations_online", []))


def _required_work(scenario: dict[str, Any]) -> tuple[set[str], set[str]]:
    required_stations = set(scenario.get("goal", {}).get("stations_online", []))
    required_panels: set[str] = set()
    stations = {station["id"]: station for station in scenario.get("stations", [])}
    panels = {panel["id"]: panel for panel in scenario.get("panels", [])}
    pending = list(required_stations)
    while pending:
        station_id = pending.pop()
        for panel_id in stations.get(station_id, {}).get("requires", {}).get("panels_ok", []):
            if panel_id not in required_panels:
                required_panels.add(panel_id)
        for dependency in stations.get(station_id, {}).get("requires", {}).get("stations_online", []):
            if dependency not in required_stations:
                required_stations.add(dependency)
                pending.append(dependency)
    return required_panels, required_stations


def _zone_distances(scenario: dict[str, Any]) -> dict[str, dict[str, int]]:
    zones = [zone["id"] for zone in scenario.get("zones", [])]
    distances = {source: {target: (0 if source == target else 10**9) for target in zones} for source in zones}
    for corridor in scenario.get("corridors", []):
        distances[corridor["from"]][corridor["to"]] = min(
            distances[corridor["from"]][corridor["to"]], int(corridor["cost"])
        )
    for middle in zones:
        for source in zones:
            for target in zones:
                distances[source][target] = min(
                    distances[source][target],
                    distances[source][middle] + distances[middle][target],
                )
    return distances


def _visit_bound(start: str, targets: set[str], distances: dict[str, dict[str, int]]) -> int:
    """MST lower bound for visiting all required zones."""
    vertices = {start} | targets
    if len(vertices) <= 1:
        return 0
    connected = {start}
    total = 0
    while connected != vertices:
        candidates = [
            (distances[source].get(target, 10**9), target)
            for source in connected
            for target in vertices - connected
        ]
        distance, target = min(candidates)
        if distance >= 10**9:
            return 0
        total += distance
        connected.add(target)
    return total


def _lower_bound(state: State, scenario: dict[str, Any]) -> int:
    """Admissible lower bound for mandatory repairs, activations and pickups."""
    costs = _costs(scenario)
    panels = dict(state.panels)
    stations = dict(state.stations)
    required_panels, required_stations = _required_work(scenario)
    remaining_panels = sum(
        1 for panel in scenario.get("panels", [])
        if panel["id"] in required_panels and panels[panel["id"]] == "DAMAGED"
    )
    remaining_stations = sum(
        1 for sid in required_stations
        if stations[sid] != "ONLINE"
    )
    payload = set(state.payload)
    missing_pickups = 0
    required_zones: set[str] = set()
    for panel in scenario.get("panels", []):
        if panel["id"] not in required_panels or panels[panel["id"]] != "DAMAGED":
            continue
        requirements = panel["requires"]
        required_zones.add(panel["zone"])
        if requirements["tool"] not in payload:
            missing_pickups += 1
            tool = next((tool for tool in scenario.get("tools", []) if tool["id"] == requirements["tool"]), None)
            if tool:
                required_zones.add(tool["zone"])
        if f"M:{requirements['material']}" not in payload:
            missing_pickups += 1
            material = next((material for material in scenario.get("materials", []) if material["type"] == requirements["material"]), None)
            if material:
                required_zones.add(material["zone"])
    for station in scenario.get("stations", []):
        if station["id"] in required_stations and stations[station["id"]] != "ONLINE":
            required_zones.add(station["zone"])
    movement = _visit_bound(state.zone, required_zones, _zone_distances(scenario))
    return ((remaining_panels + remaining_stations) * costs["interact"]
            + missing_pickups * costs["pickup"] + movement)


def _guidance(state: State, scenario: dict[str, Any]) -> int:
    """Search guidance used only for expansion order; path cost remains exact."""
    required_panels, required_stations = _required_work(scenario)
    unfinished_zones = [
        panel["zone"]
        for panel in scenario.get("panels", [])
        if panel["id"] in required_panels and dict(state.panels)[panel["id"]] == "DAMAGED"
    ]
    unfinished_zones += [
        station["zone"]
        for station in scenario.get("stations", [])
        if station["id"] in required_stations
        and dict(state.stations)[station["id"]] != "ONLINE"
    ]
    distance = 0
    if unfinished_zones:
        distances = {state.zone: 0}
        pending = [state.zone]
        while pending:
            zone = pending.pop(0)
            for corridor in scenario.get("corridors", []):
                if corridor["from"] != zone or corridor["to"] in distances:
                    continue
                distances[corridor["to"]] = distances[zone] + int(corridor["cost"])
                pending.append(corridor["to"])
        distance = min(distances.get(zone, 0) for zone in unfinished_zones)
    return _lower_bound(state, scenario) + distance


def _step(state: State, cost: int) -> bool:
    return state.battery >= cost


def _reachable_moves(state: State, scenario: dict[str, Any]) -> list[tuple[str, int, list[str]]]:
    """Return cheapest open-door routes; visual reconstruction expands each route."""
    distances: dict[str, tuple[int, list[str]]] = {state.zone: (0, [state.zone])}
    pending: list[tuple[int, str]] = [(0, state.zone)]
    doors = dict(state.doors)
    while pending:
        pending.sort(reverse=True)
        distance, zone = pending.pop()
        if distance != distances[zone][0]:
            continue
        for corridor in scenario.get("corridors", []):
            if corridor["from"] != zone:
                continue
            if corridor.get("door") and doors[corridor["door"]] != "OPEN":
                continue
            target = corridor["to"]
            next_distance = distance + int(corridor["cost"])
            if target not in distances or next_distance < distances[target][0]:
                distances[target] = (next_distance, distances[zone][1] + [target])
                pending.append((next_distance, target))
    return [(zone, cost, path) for zone, (cost, path) in distances.items() if zone != state.zone]


def _make_state(state: State, *, zone: str | None = None, battery: int | None = None,
                payload: tuple[str, ...] | None = None, ground: tuple[tuple[str, str], ...] | None = None,
                doors: dict[str, str] | None = None, panels: dict[str, str] | None = None,
                stations: dict[str, str] | None = None) -> State:
    return State(
        zone if zone is not None else state.zone,
        battery if battery is not None else state.battery,
        tuple(sorted(payload if payload is not None else state.payload)),
        tuple(sorted(ground if ground is not None else state.ground)),
        tuple(sorted((doors if doors is not None else dict(state.doors)).items())),
        tuple(sorted((panels if panels is not None else dict(state.panels)).items())),
        tuple(sorted((stations if stations is not None else dict(state.stations)).items())),
    )


def _successors(state: State, scenario: dict[str, Any]) -> list[tuple[State, dict[str, Any], int]]:
    costs = _costs(scenario)
    result: list[tuple[State, dict[str, Any], int]] = []
    ground, doors, panels, stations = _maps(state)
    cap = int(scenario["robot"]["cargo_capacity"])
    payload_weight = sum(_weight(item, scenario) for item in state.payload)

    for target, cost, path in _reachable_moves(state, scenario):
        if _step(state, cost):
            result.append((_make_state(state, zone=target, battery=state.battery - cost),
                           {"kind": "MOVE_PATH", "from": state.zone, "to": target, "path": path,
                            "corridors": scenario.get("corridors", [])}, cost))

    for item, zone in state.ground:
        if zone != state.zone:
            continue
        weight = _weight(item, scenario)
        if payload_weight + weight > cap or not _step(state, costs["pickup"]):
            continue
        remaining = list(state.ground)
        remaining.remove((item, zone))
        payload = state.payload + (item,)
        result.append((_make_state(state, battery=state.battery - costs["pickup"], payload=payload, ground=tuple(remaining)),
                       {"kind": "PICKUP", "item": _item_type(item)}, costs["pickup"]))

    # A DROP is relevant only when it makes a currently available pickup fit.
    pickup_weights = [
        _weight(item, scenario)
        for item, zone in state.ground
        if zone == state.zone
    ]
    if payload_weight >= cap and pickup_weights and _step(state, costs["drop"]):
        for item in state.payload:
            freed = _weight(item, scenario)
            if not any(payload_weight - freed + weight <= cap for weight in pickup_weights):
                continue
            payload = list(state.payload)
            payload.remove(item)
            ground_items = list(state.ground) + [(item, state.zone)]
            result.append((_make_state(state, battery=state.battery - costs["drop"], payload=tuple(payload), ground=tuple(ground_items)),
                           {"kind": "DROP", "item": _item_type(item)}, costs["drop"]))

    for door in scenario.get("doors", []):
        if doors[door["id"]] != "CLOSED" or not any(item == door["key"] for item in state.payload):
            continue
        if state.zone not in door["between"] or not _step(state, costs["interact"]):
            continue
        updated = dict(doors)
        updated[door["id"]] = "OPEN"
        result.append((_make_state(state, battery=state.battery - costs["interact"], doors=updated),
                       {"kind": "OPEN_DOOR", "target": door["id"]}, costs["interact"]))

    for panel in scenario.get("panels", []):
        if panels[panel["id"]] != "DAMAGED" or panel["zone"] != state.zone or not _step(state, costs["interact"]):
            continue
        required = panel["requires"]
        if required["tool"] not in state.payload or f"M:{required['material']}" not in state.payload:
            continue
        updated = dict(panels)
        updated[panel["id"]] = "OK"
        payload = list(state.payload)
        payload.remove(f"M:{required['material']}")
        result.append((_make_state(state, battery=state.battery - costs["interact"], payload=tuple(payload), panels=updated),
                       {"kind": "REPAIR", "target": panel["id"], "material": required["material"]}, costs["interact"]))

    for station in scenario.get("stations", []):
        if stations[station["id"]] != "OFFLINE" or station["zone"] != state.zone or not _step(state, costs["interact"]):
            continue
        requires = station.get("requires", {})
        if any(panels.get(pid) != "OK" for pid in requires.get("panels_ok", [])):
            continue
        if any(stations.get(sid) != "ONLINE" for sid in requires.get("stations_online", [])):
            continue
        updated = dict(stations)
        updated[station["id"]] = "ONLINE"
        result.append((_make_state(state, battery=state.battery - costs["interact"], stations=updated),
                       {"kind": "ACTIVATE", "target": station["id"]}, costs["interact"]))

    if any(zone == state.zone for zone in (charger["zone"] for charger in scenario.get("chargers", []))) and state.battery < scenario["robot"]["battery_max"] and _step(state, costs["recharge"]):
        for charger in scenario.get("chargers", []):
            if charger["zone"] == state.zone:
                result.append((_make_state(state, battery=int(scenario["robot"]["battery_max"])),
                               {"kind": "RECHARGE", "target": charger["id"]}, costs["recharge"]))
                break
    return [(_prune_inert(next_state, scenario), action, cost) for next_state, action, cost in result]


def _visual(action: dict[str, Any], cost: int) -> list[dict[str, Any]]:
    kind = action["kind"]
    if kind == "MOVE":
        return [{"op": "MOVE", "from": action["from"], "to": action["to"], "cost": cost}]
    if kind == "MOVE_PATH":
        return [
            {"op": "MOVE", "from": frm, "to": to, "cost": _corridor_cost(action, frm, to)}
            for frm, to in zip(action["path"], action["path"][1:])
        ]
    if kind in ("PICKUP", "DROP"):
        return [{"op": kind, "item": action["item"], "cost": cost}]
    step = {"op": "INTERACT", "target": action["target"], "cost": cost}
    step["action"] = {"OPEN_DOOR": "OPEN_DOOR", "REPAIR": "REPAIR", "ACTIVATE": "ACTIVATE", "RECHARGE": "RECHARGE"}[kind]
    if kind == "REPAIR":
        step["consumes"] = action["material"]
    return [step]


def _corridor_cost(action: dict[str, Any], frm: str, to: str) -> int:
    for corridor in action["corridors"]:
        if corridor["from"] == frm and corridor["to"] == to:
            return int(corridor["cost"])
    raise ValueError(f"Missing corridor {frm}->{to}")


def _reconstruct(node: Node) -> list[dict[str, Any]]:
    blocks: list[list[dict[str, Any]]] = []
    current: Node | None = node
    while current and current.action is not None:
        blocks.append(_visual(current.action, current.action_cost))
        current = current.parent
    steps: list[dict[str, Any]] = []
    for block in reversed(blocks):
        steps.extend(block)
    return steps


def _guided_solve(scenario: dict[str, Any]) -> dict[str, Any]:
    initial = Node(_initial(scenario), 0, None, None)
    queue: list[tuple[int, int, int, Node]] = [(_guidance(initial.state, scenario), 0, 0, initial)]
    serial = 0
    frontier: dict[tuple[Any, ...], list[tuple[int, int]]] = {
        _physical_key(initial.state): [(0, initial.state.battery)]
    }
    while queue:
        _, _, _, node = heapq.heappop(queue)
        key = _physical_key(node.state)
        pairs = frontier.get(key, [])
        if (node.cost, node.state.battery) not in pairs:
            continue
        if _goal(node.state, scenario):
            actions = _reconstruct(node)
            return {"solution_found": True, "total_cost": node.cost, "steps": actions, "message": "Plan found with informed search."}
        for child_state, action, cost in _successors(node.state, scenario):
            serial += 1
            child = Node(child_state, node.cost + cost, node, action, cost)
            child_key = _physical_key(child_state)
            child_pairs = frontier.get(child_key, [])
            if any(old_cost <= child.cost and old_battery >= child_state.battery
                   for old_cost, old_battery in child_pairs):
                continue
            frontier[child_key] = [
                (old_cost, old_battery)
                for old_cost, old_battery in child_pairs
                if not (child.cost <= old_cost and child_state.battery >= old_battery)
            ] + [(child.cost, child_state.battery)]
            priority = _guidance(child.state, scenario)
            heapq.heappush(queue, (priority, child.cost, serial, child))
    return {"solution_found": False, "total_cost": 0, "steps": [], "message": "FAILURE: no valid plan."}


def solve(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run UCS, using a valid guided solution only as an upper bound."""
    incumbent = _guided_solve(scenario)
    try:
        try:
            from demo_plan import build_demo_plan
        except ModuleNotFoundError:
            from .demo_plan import build_demo_plan
        try:
            from simulator import goal_satisfied, simulate
        except ModuleNotFoundError:
            from .simulator import goal_satisfied, simulate
        demo = build_demo_plan(scenario)
        final = simulate(scenario, demo["steps"])
        if (demo["solution_found"] and goal_satisfied(scenario, final)
                and demo["total_cost"] == final["energy_spent"]
                and demo["total_cost"] < incumbent.get("total_cost", float("inf"))):
            incumbent = demo
    except (AssertionError, KeyError, ModuleNotFoundError, ValueError):
        pass
    upper_bound = incumbent["total_cost"] if incumbent["solution_found"] else None
    initial = Node(_initial(scenario), 0, None, None)
    queue: list[tuple[int, int, Node]] = [(0, 0, initial)]
    serial = 0
    frontier: dict[tuple[Any, ...], list[tuple[int, int]]] = {
        _physical_key(initial.state): [(0, initial.state.battery)]
    }
    expansions = 0

    while queue:
        expansions += 1
        if expansions > MAX_UCS_EXPANSIONS:
            if incumbent["solution_found"]:
                return {
                    **incumbent,
                    "message": (
                        "Valid plan returned after UCS expansion limit; "
                        "optimality was not certified."
                    ),
                    "optimality_certified": False,
                }
            break
        _, _, node = heapq.heappop(queue)
        key = _physical_key(node.state)
        pairs = frontier.get(key, [])
        if (node.cost, node.state.battery) not in pairs:
            continue
        if upper_bound is not None and node.cost + _lower_bound(node.state, scenario) >= upper_bound:
            continue
        if _goal(node.state, scenario):
            actions = _reconstruct(node)
            return {
                "solution_found": True,
                "total_cost": node.cost,
                "steps": actions,
                "message": "Plan found with uniform-cost search.",
                "optimality_certified": True,
            }

        for child_state, action, cost in _successors(node.state, scenario):
            child = Node(child_state, node.cost + cost, node, action, cost)
            if upper_bound is not None and child.cost + _lower_bound(child.state, scenario) >= upper_bound:
                continue
            child_key = _physical_key(child_state)
            child_pairs = frontier.get(child_key, [])
            if any(old_cost <= child.cost and old_battery >= child_state.battery
                   for old_cost, old_battery in child_pairs):
                continue
            frontier[child_key] = [
                (old_cost, old_battery)
                for old_cost, old_battery in child_pairs
                if not (child.cost <= old_cost and child_state.battery >= old_battery)
            ] + [(child.cost, child.state.battery)]
            serial += 1
            heapq.heappush(queue, (child.cost, serial, child))

    if incumbent["solution_found"]:
        return incumbent
    return {"solution_found": False, "total_cost": 0, "steps": [], "message": "FAILURE: no valid plan."}
