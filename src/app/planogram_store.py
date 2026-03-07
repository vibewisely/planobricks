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

STORE_SCHEMATICS_DIR = os.path.join(os.path.dirname(__file__), "data", "store_schematics")

DELTA_TABLE = "serverless_stable_wunnava_catalog.planobricks_reference.schematics"
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "d2634d1ef348571a")
STORE_IMAGES_VOLUME = (
    "/Volumes/serverless_stable_wunnava_catalog"
    "/planobricks_reference/inputs/images/store_images"
)


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


def save(
    key_str: str,
    sp: SchematicPlanogram,
    origin: str = "custom",
    source_image_path: str = "",
    created_by: str = "editor",
) -> None:
    sp_dict = schematic_to_dict(sp, origin=origin)
    ALL_SCHEMATICS[key_str] = sp_dict
    _save_to_disk()
    _save_to_delta("store-a", key_str, sp_dict, source_image_path, created_by)


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


def _save_to_delta(
    store_id: str,
    key_str: str,
    sp_dict: dict,
    source_image_path: str = "",
    created_by: str = "editor",
) -> None:
    """Persist a schematic to the Delta table (best-effort)."""
    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()

        kt = _key_tuple(key_str)
        pid, ns, sr = kt
        rows_json = json.dumps(sp_dict.get("rows", []))
        num_rows = len(sp_dict.get("rows", []))
        total_products = sum(len(r.get("brands", [])) for r in sp_dict.get("rows", []))
        origin = sp_dict.get("origin", "custom")
        source_filenames = ",".join(sp_dict.get("source_images", []))
        store_vol = f"{STORE_IMAGES_VOLUME}/{store_id}" if store_id != "store-a" else ""

        # Escape single quotes in JSON for SQL
        rows_json_escaped = rows_json.replace("'", "''")
        source_image_path_escaped = source_image_path.replace("'", "''")
        source_filenames_escaped = source_filenames.replace("'", "''")

        sql = f"""
        MERGE INTO {DELTA_TABLE} AS t
        USING (SELECT '{store_id}' AS store_id, '{key_str}' AS schema_key) AS s
        ON t.store_id = s.store_id AND t.schema_key = s.schema_key
        WHEN MATCHED THEN UPDATE SET
          planogram_id = '{pid}',
          num_shelves = '{ns}',
          shelf_rank = '{sr}',
          rows_json = '{rows_json_escaped}',
          num_rows = {num_rows},
          total_products = {total_products},
          origin = '{origin}',
          source_image_path = '{source_image_path_escaped}',
          source_image_filenames = '{source_filenames_escaped}',
          store_volume_location = '{store_vol}',
          created_by = '{created_by}',
          updated_at = current_timestamp()
        WHEN NOT MATCHED THEN INSERT (
          schema_key, store_id, planogram_id, num_shelves, shelf_rank,
          rows_json, num_rows, total_products, origin,
          source_image_path, source_image_filenames, store_volume_location,
          created_by, created_at, updated_at
        ) VALUES (
          '{key_str}', '{store_id}', '{pid}', '{ns}', '{sr}',
          '{rows_json_escaped}', {num_rows}, {total_products}, '{origin}',
          '{source_image_path_escaped}', '{source_filenames_escaped}', '{store_vol}',
          '{created_by}', current_timestamp(), current_timestamp()
        )
        """

        resp = w.api_client.do(
            "POST",
            "/api/2.0/sql/statements",
            body={
                "warehouse_id": WAREHOUSE_ID,
                "statement": sql,
                "wait_timeout": "30s",
            },
        )
        status = resp.get("status", {}).get("state", "UNKNOWN") if isinstance(resp, dict) else "OK"
        print(f"[PlanoBricks] Delta save {key_str} for {store_id}: {status}", flush=True)

    except Exception as e:
        log.warning("Could not save schematic to Delta: %s", e)
        print(f"[PlanoBricks] Delta save failed: {e}", flush=True)


# ─── Store-scoped helpers ────────────────────────────────────────

def _store_path(store_id: str) -> str:
    return os.path.join(STORE_SCHEMATICS_DIR, f"{store_id}.json")


def _store_volume_path(store_id: str) -> str:
    return (
        "/Volumes/serverless_stable_wunnava_catalog"
        f"/planobricks_reference/inputs/schematics_{store_id}.json"
    )


def _load_store_from_delta(store_id: str) -> dict[str, dict]:
    """Load schematics for a store from the Delta table."""
    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        sql = (
            f"SELECT schema_key, planogram_id, num_shelves, shelf_rank, "
            f"rows_json, origin, source_image_filenames, source_image_path "
            f"FROM {DELTA_TABLE} WHERE store_id = '{store_id}'"
        )
        resp = w.api_client.do(
            "POST",
            "/api/2.0/sql/statements",
            body={
                "warehouse_id": WAREHOUSE_ID,
                "statement": sql,
                "wait_timeout": "30s",
            },
        )
        if not isinstance(resp, dict):
            return {}

        status = resp.get("status", {}).get("state", "")
        if status != "SUCCEEDED":
            print(f"[PlanoBricks] Delta load failed: {status}", flush=True)
            return {}

        manifest = resp.get("manifest", {})
        columns = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]
        data_array = resp.get("result", {}).get("data_array", [])
        if not data_array or not columns:
            return {}

        result: dict[str, dict] = {}
        for row in data_array:
            row_dict = dict(zip(columns, row))
            key = row_dict["schema_key"]
            rows = json.loads(row_dict.get("rows_json") or "[]")
            source_imgs = [
                s.strip()
                for s in (row_dict.get("source_image_filenames") or "").split(",")
                if s.strip()
            ]
            result[key] = {
                "planogram_id": row_dict["planogram_id"],
                "num_shelves": row_dict["num_shelves"],
                "shelf_rank": row_dict["shelf_rank"],
                "rows": rows,
                "source_images": source_imgs,
                "origin": row_dict.get("origin", "custom"),
                "updated_at": time.time(),
            }

        if result:
            print(
                f"[PlanoBricks] Loaded {len(result)} schematics for {store_id} from Delta",
                flush=True,
            )
        return result

    except Exception as e:
        print(f"[PlanoBricks] Delta load failed for {store_id}: {e}", flush=True)
        return {}


def load_store_schematics(store_id: str) -> dict[str, dict]:
    """Load schematics for a specific store.

    Tries: local file → UC Volume → Delta table.
    Caches locally on successful remote load.
    """
    local = _store_path(store_id)
    if os.path.isfile(local):
        try:
            with open(local) as f:
                return json.load(f)
        except Exception:
            pass

    # Try UC Volume
    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        resp = w.files.download(_store_volume_path(store_id))
        data = json.loads(resp.contents.read())
        os.makedirs(STORE_SCHEMATICS_DIR, exist_ok=True)
        with open(local, "w") as f:
            json.dump(data, f)
        print(f"[PlanoBricks] Loaded schematics for {store_id} from UC Volume", flush=True)
        return data
    except Exception:
        pass

    # Try Delta table as final fallback
    data = _load_store_from_delta(store_id)
    if data:
        # Cache locally for fast subsequent loads
        os.makedirs(STORE_SCHEMATICS_DIR, exist_ok=True)
        with open(local, "w") as f:
            json.dump(data, f, indent=2)
        # Also sync to UC Volume for next time
        try:
            from io import BytesIO

            from databricks.sdk import WorkspaceClient

            w = WorkspaceClient()
            content = json.dumps(data, indent=2).encode()
            w.files.upload(_store_volume_path(store_id), BytesIO(content), overwrite=True)
        except Exception:
            pass
        return data

    return {}


def save_store_schematics(store_id: str, schematics: dict[str, dict]) -> None:
    """Persist schematics for a specific store."""
    os.makedirs(STORE_SCHEMATICS_DIR, exist_ok=True)
    local = _store_path(store_id)
    with open(local, "w") as f:
        json.dump(schematics, f, indent=2)
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        content = json.dumps(schematics, indent=2).encode()
        from io import BytesIO
        w.files.upload(_store_volume_path(store_id), BytesIO(content), overwrite=True)
    except Exception as e:
        log.warning("Could not save store schematics to UC Volume: %s", e)


def save_for_store(
    store_id: str,
    key_str: str,
    sp: SchematicPlanogram,
    origin: str = "custom",
    source_image_path: str = "",
    created_by: str = "editor",
) -> None:
    """Save a single schematic for a store."""
    sp_dict = schematic_to_dict(sp, origin=origin)
    store_data = load_store_schematics(store_id)
    store_data[key_str] = sp_dict
    save_store_schematics(store_id, store_data)
    _save_to_delta(store_id, key_str, sp_dict, source_image_path, created_by)


def list_store_keys(store_id: str) -> list[dict]:
    """List schematic keys for a specific store."""
    store_data = load_store_schematics(store_id)
    result = []
    for ks in sorted(store_data.keys()):
        d = store_data[ks]
        total = sum(len(r["brands"]) for r in d["rows"])
        result.append({
            "key": ks,
            "origin": d.get("origin", "auto"),
            "num_rows": len(d["rows"]),
            "total_products": total,
            "source_images": len(d.get("source_images", [])),
        })
    return result
