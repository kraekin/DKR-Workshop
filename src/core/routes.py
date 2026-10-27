"""Existing checkpoint lanes and global loaded AI graph; no structural edits.

Sources: level_object_entries.h:131/196, objects.c:5530/7347, racer.c:9060.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import numpy as np

from src.core.objects import LevelObject
from src.core.placement import patch_entry

LATERAL = ("unkB", "unkC", "unkD", "unkE")
HEIGHT = ("unkF", "unk10", "unk11", "unk12")
BEHAVIOR = ("unk13", "unk14", "unk15", "unk16")


def lane_point(obj: LevelObject, lane: int) -> tuple[float, float, float]:
    if obj.definition.behavior_id != 13 or lane not in range(4):
        raise ValueError("Select a checkpoint and AI lane 0..3")
    scale, yaw = max(float(obj.value("scale")), 5) / 32, obj.yaw or 0
    lateral, vertical = obj.value(LATERAL[lane]), obj.value(HEIGHT[lane])
    x, y, z = obj.position
    return x + scale * math.cos(yaw) * lateral, y + scale * vertical, z - scale * math.sin(yaw) * lateral


def lane_entry(obj: LevelObject, lane: int, point: tuple[float, float, float]) -> bytes:
    """Project a world target onto the checkpoint's lateral/vertical plane.

    The longitudinal component has no stored lane byte. Clamp the two signed8
    values independently, then preview the quantized actual control point.
    """
    lane_point(obj, lane)
    if len(point) != 3 or not np.all(np.isfinite(point)):
        raise ValueError("Lane target needs three finite coordinates")
    delta = np.asarray(point, np.float64) - obj.position
    scale, yaw = max(float(obj.value("scale")), 5) / 32, obj.yaw or 0
    lateral = round((math.cos(yaw) * delta[0] - math.sin(yaw) * delta[2]) / scale)
    vertical = round(delta[1] / scale)
    return patch_entry(obj, parameters={LATERAL[lane]: min(127, max(-128, lateral)),
                                        HEIGHT[lane]: min(127, max(-128, vertical))})


def connection_entry(obj: LevelObject, slot: int, target: int,
                     objects: tuple[LevelObject, ...]) -> bytes:
    if obj.definition.behavior_id != 16 or type(slot) is not int or slot not in range(4):
        raise ValueError("Select an AI node and connection slot 0..3")
    if type(target) is not int or (target != 255 and target not in range(128)):
        raise ValueError("AI targets must be IDs 0..127 or 255 (no connection)")
    if target != 255:
        matches = [other for other in objects if other.definition.behavior_id == 16 and other.value("nodeID") == target]
        if len(matches) != 1:
            raise ValueError("Target ID must identify exactly one loaded AI node")
        if matches[0].key == obj.key:
            raise ValueError("Choose another node; self connections are not created")
        if any(value == target for index, value in enumerate(obj.value("adjacent")) if index != slot):
            raise ValueError("That target is already present in another connection slot")
    links = list(obj.value("adjacent"))
    links[slot] = target
    return patch_entry(obj, parameters={"adjacent": tuple(links)})


@dataclass(frozen=True)
class RouteIssue:
    code: str
    message: str
    keys: tuple[tuple[int, int], ...]


def route_diagnostics(objects: tuple[LevelObject, ...], checkpoint_sets: tuple[int, int, int]) -> tuple[RouteIssue, ...]:
    """Report existing issues without repairing, renumbering or hiding raw data."""
    issues: list[RouteIssue] = []
    checkpoints: dict[tuple[int, int, bool], list[LevelObject]] = defaultdict(list)
    nodes: dict[int, list[LevelObject]] = defaultdict(list)
    for obj in objects:
        if obj.definition.behavior_id == 13:
            checkpoints[int(obj.value("vehicleType")), int(obj.value("index")), bool(obj.value("isAltCheckpoint"))].append(obj)
        elif obj.definition.behavior_id == 16:
            node_id = int(obj.value("nodeID"))
            if node_id >= 128:
                issues.append(RouteIssue("dynamic-id" if node_id == 255 else "invalid-id",
                                        f"AI ID {node_id}: runtime-assigned" if node_id == 255 else f"AI ID {node_id} is outside the fixed table 0..127", (obj.key,)))
            else:
                nodes[node_id].append(obj)
    for (group, index, alternate), matches in sorted(checkpoints.items()):
        keys = tuple(obj.key for obj in matches)
        name = f"Set {group} / {'alternate' if alternate else 'main'} checkpoint {index}"
        if len(matches) > 1:
            issues.append(RouteIssue("duplicate-checkpoint", f"{name}: {len(matches)} entries share the same index", keys))
        if alternate and (group, index, False) not in checkpoints:
            issues.append(RouteIssue("orphan-alternate", f"{name}: no paired main checkpoint", keys))
    for group in sorted({key[0] for key in checkpoints}):
        runtime_ids: dict[int, list[LevelObject]] = defaultdict(list)
        for (set_id, index, alternate), matches in checkpoints.items():
            if set_id == group:
                runtime_ids[index + (255 if alternate else 0)].extend(matches)
        if 255 in runtime_ids and (group, 255, False) in checkpoints and (group, 0, True) in checkpoints:
            issues.append(RouteIssue("checkpoint-sort-collision", f"Set {group}: main index 255 and alternate index 0 share runtime sort ID 255", tuple(obj.key for obj in runtime_ids[255])))
        main = sorted(index for (set_id, index, alt) in checkpoints if set_id == group and not alt)
        if main and main != list(range(len(main))):
            issues.append(RouteIssue("checkpoint-order", f"Info · set {group}: gaps in main indexes (allowed; game sorts stored indexes)",
                                     tuple(obj.key for key, matches in checkpoints.items() if key[0] == group for obj in matches)))
        count = sum(len(matches) for key, matches in checkpoints.items() if key[0] == group)
        if count > 60:  # MAX_CHECKPOINTS in src/objects.c:45.
            issues.append(RouteIssue("checkpoint-capacity", f"Set {group}: {count} entries exceed MAX_CHECKPOINTS=60", ()))
    if checkpoints:
        main_sets = {key[0] for key in checkpoints if not key[2]}
        for vehicle, group in zip(("Car", "Hovercraft", "Plane"), checkpoint_sets):
            if group not in main_sets:
                issues.append(RouteIssue("unmapped-set", f"{vehicle} selects checkpoint set {group}, which has no main checkpoints", ()))
    for node_id, matches in sorted(nodes.items()):
        if len(matches) > 1:
            issues.append(RouteIssue("duplicate-node", f"AI ID {node_id}: {len(matches)} loaded entries share an ID", tuple(obj.key for obj in matches)))
        for obj in matches:
            links = obj.value("adjacent")
            for slot, target in enumerate(links):
                if target == 255:
                    continue
                if target not in nodes:
                    issues.append(RouteIssue("dangling-link", f"AI {node_id} slot {slot} → {target}: target missing or outside 0..127", (obj.key,)))
                elif len(nodes[target]) > 1:
                    issues.append(RouteIssue("ambiguous-link", f"AI {node_id} slot {slot} → {target}: target ID is duplicated", (obj.key,)))
                if target == node_id:
                    issues.append(RouteIssue("self-link", f"AI {node_id} slot {slot}: self connection", (obj.key,)))
            if len([v for v in links if v != 255]) != len({v for v in links if v != 255}):
                issues.append(RouteIssue("duplicate-link", f"AI {node_id}: repeated target in its connection slots", (obj.key,)))
    return tuple(issues)


def route_label(obj: LevelObject, checkpoint_sets: tuple[int, int, int]) -> str:
    if obj.definition.behavior_id == 13:
        group = obj.value("vehicleType")
        vehicles = "/".join(v for v, s in zip(("Car", "Hovercraft", "Plane"), checkpoint_sets) if s == group) or "unmapped"
        return f"CP {obj.value('index')} · set {group} · {'alternate' if obj.value('isAltCheckpoint') else 'main'} · {vehicles}"
    if obj.definition.behavior_id == 16:
        return f"AI {obj.value('nodeID')} → {', '.join('—' if v == 255 else str(v) for v in obj.value('adjacent'))}"
    return obj.definition.name
