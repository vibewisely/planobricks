"""Persistent storage for schematic planogram references.

Schematics are stored as JSON — locally in the app's data/ directory for
immediate access, and optionally synced to a UC Volume for persistence
across deployments.

Each schematic has a unique string key (e.g. "P01/3s/R1") and an origin
("auto" for consensus-generated, "custom" for user-created/edited).
"""

from __future__ import annotations

import json
import logging
import os
import time

from planogram_engine import SchematicPlanogram, SchematicRow, SchematicKey

log = logging.getLogger(__name__)

LOCAL_PATH = os.path.join(os.path.dirname(__file__), "data", "schematics.json")
VOLUME_PATH = (
    "/Volumes/serverless_stable_wunnava_catalog"
    "/planobricks_reference/inputs/schematics.json"
)

ALL_SCHEMATICS: dict[str, dict] = {}


def _key_str(key: SchematicKey | str) -> str:
    if isinstance(key, tuple):
        pid, ns, sr = key
        return f"P{pid}/{ns}s/R{sr}"
    return key


def _key_tuple(key_str: str) -> SchematicKey:
    parts = key_str.replace("P", "").replace("s/R", "/").split("/")
    return (parts[0], parts[1], parts[2])


def schematic_to_dict(sp: SchematicPlanogram, origin: str = "auto") -> dict:
    return {
        "planogram_id": sp.planogram_id,
        "num_shelves": sp.num_shelves,
        "shelf_rank": sp.shelf_rank,
        "rows": [{"row_index": r.row_index, "brands": r.brands} for r in sp.rows],
        "source_images": sp.source_images,
        "origin": origin,
        "updated_at": time.time(),
    }


def dict_to_schematic(d: dict) -> SchematicPlanogram:
    rows = [SchematicRow(row_index=r["row_index"], brands=r["brands"]) for r in d["rows"]]
    return SchematicPlanogram(
        planogram_id=d["planogram_id"],
        num_shelves=d["num_shelves"],
        shelf_rank=d["shelf_rank"],
        rows=rows,
        source_images=d.get("source_images", []),
    )


def init_from_auto(schematics: dict[SchematicKey, SchematicPlanogram]) -> None:
    """Initialize the store from auto-generated schematics, preserving custom edits."""
    saved = _load_from_disk()
    for key, sp in schematics.items():
        ks = _key_str(key)
        if ks in saved and saved[ks].get("origin") == "custom":
            ALL_SCHEMATICS[ks] = saved[ks]
        else:
            ALL_SCHEMATICS[ks] = schematic_to_dict(sp, origin="auto")

    for ks, d in saved.items():
        if ks not in ALL_SCHEMATICS:
            ALL_SCHEMATICS[ks] = d


def get_all() -> dict[str, dict]:
    return ALL_SCHEMATICS


def get(key_str: str) -> SchematicPlanogram | None:
    d = ALL_SCHEMATICS.get(key_str)
    return dict_to_schematic(d) if d else None


def get_by_tuple(key: SchematicKey) -> SchematicPlanogram | None:
    return get(_key_str(key))


def save(key_str: str, sp: SchematicPlanogram, origin: str = "custom") -> None:
    ALL_SCHEMATICS[key_str] = schematic_to_dict(sp, origin=origin)
    _save_to_disk()


def delete(key_str: str) -> bool:
    if key_str in ALL_SCHEMATICS:
        del ALL_SCHEMATICS[key_str]
        _save_to_disk()
        return True
    return False


def clone(src_key: str, new_key: str) -> SchematicPlanogram | None:
    src = ALL_SCHEMATICS.get(src_key)
    if not src:
        return None
    sp = dict_to_schematic(src)
    kt = _key_tuple(new_key)
    sp.planogram_id, sp.num_shelves, sp.shelf_rank = kt
    sp.source_images = []
    save(new_key, sp, origin="custom")
    return sp


def list_keys() -> list[dict]:
    """Return summary info for all schematics, sorted by key."""
    result = []
    for ks in sorted(ALL_SCHEMATICS.keys()):
        d = ALL_SCHEMATICS[ks]
        total = sum(len(r["brands"]) for r in d["rows"])
        result.append({
            "key": ks,
            "origin": d.get("origin", "auto"),
            "num_rows": len(d["rows"]),
            "total_products": total,
            "source_images": len(d.get("source_images", [])),
        })
    return result


def _load_from_disk() -> dict[str, dict]:
    for path in [LOCAL_PATH, VOLUME_PATH]:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception as e:
                log.warning("Failed to load schematics from %s: %s", path, e)

    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        resp = w.files.download(VOLUME_PATH)
        data = json.loads(resp.contents.read())
        os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
        with open(LOCAL_PATH, "w") as f:
            json.dump(data, f)
        return data
    except Exception:
        pass

    return {}


def _save_to_disk() -> None:
    os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
    with open(LOCAL_PATH, "w") as f:
        json.dump(ALL_SCHEMATICS, f, indent=2)

    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        content = json.dumps(ALL_SCHEMATICS, indent=2).encode()
        from io import BytesIO
        w.files.upload(VOLUME_PATH, BytesIO(content), overwrite=True)
        log.info("Schematics saved to UC Volume")
    except Exception as e:
        log.warning("Could not save schematics to UC Volume: %s", e)
