from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class BalanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BalancePack:
    meta: dict
    resources: list[str]
    units_by_id: dict[str, dict]
    buildings_by_id: dict[str, dict]
    races_by_id: dict[str, dict]
    tech_by_id: dict[str, dict]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise BalanceError(f"Не удалось прочитать {path}: {e!r}")


def _require_id_map(items: list[dict], *, kind: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:
        if not isinstance(it, dict):
            raise BalanceError(f"{kind}: элемент должен быть object")
        _id = it.get("id")
        if not isinstance(_id, str) or not _id.strip():
            raise BalanceError(f"{kind}: у элемента нет корректного id")
        if _id in out:
            raise BalanceError(f"{kind}: дублирующийся id={_id}")
        out[_id] = it
    return out


def _validate_meta(meta: dict) -> None:
    if not isinstance(meta, dict):
        raise BalanceError("meta.json должен быть object")
    v = meta.get("schema_version")
    if v != 1:
        raise BalanceError(f"Неподдерживаемая schema_version={v}, ожидаю 1")


def _validate_resources(res: dict) -> list[str]:
    resources = res.get("resources")
    if not isinstance(resources, list) or not all(isinstance(x, str) for x in resources):
        raise BalanceError("resources.json: ожидаю resources: [string]")
    if len(set(resources)) != len(resources):
        raise BalanceError("resources.json: ресурсы не должны повторяться")
    return resources


def _validate_tech_dag(tech_by_id: dict[str, dict]) -> None:
    # DAG check by DFS colors
    color: dict[str, int] = {k: 0 for k in tech_by_id.keys()}  # 0=unseen,1=visiting,2=done

    def dfs(tid: str) -> None:
        c = color.get(tid, 0)
        if c == 1:
            raise BalanceError(f"tech: найден цикл, узел {tid}")
        if c == 2:
            return
        color[tid] = 1
        prereq = tech_by_id[tid].get("prereq", [])
        if prereq is None:
            prereq = []
        if not isinstance(prereq, list) or not all(isinstance(x, str) for x in prereq):
            raise BalanceError(f"tech: prereq у {tid} должен быть [string]")
        for p in prereq:
            if p not in tech_by_id:
                raise BalanceError(f"tech: prereq {p} у {tid} не существует")
            dfs(p)
        color[tid] = 2

    for tid in tech_by_id.keys():
        if color[tid] == 0:
            dfs(tid)


def load_balance_pack(*, base_dir: Path) -> BalancePack:
    meta = _read_json(base_dir / "meta.json")
    _validate_meta(meta)

    resources_doc = _read_json(base_dir / "resources.json")
    resources = _validate_resources(resources_doc)

    units_doc = _read_json(base_dir / "units.json")
    units = units_doc.get("units", [])
    if not isinstance(units, list):
        raise BalanceError("units.json: ожидаю units: []")
    units_by_id = _require_id_map(units, kind="units")

    buildings_doc = _read_json(base_dir / "buildings.json")
    buildings = buildings_doc.get("buildings", [])
    if not isinstance(buildings, list):
        raise BalanceError("buildings.json: ожидаю buildings: []")
    buildings_by_id = _require_id_map(buildings, kind="buildings")

    races_doc = _read_json(base_dir / "races.json")
    races = races_doc.get("races", [])
    if not isinstance(races, list):
        raise BalanceError("races.json: ожидаю races: []")
    races_by_id = _require_id_map(races, kind="races")

    tech_doc = _read_json(base_dir / "tech.json")
    tech = tech_doc.get("tech", [])
    if not isinstance(tech, list):
        raise BalanceError("tech.json: ожидаю tech: []")
    tech_by_id = _require_id_map(tech, kind="tech")
    _validate_tech_dag(tech_by_id)

    return BalancePack(
        meta=meta,
        resources=resources,
        units_by_id=units_by_id,
        buildings_by_id=buildings_by_id,
        races_by_id=races_by_id,
        tech_by_id=tech_by_id,
    )


def default_balance_dir() -> Path:
    # server/app/services/balance_service.py -> server/data/balance
    return Path(__file__).resolve().parents[2] / "data" / "balance"

