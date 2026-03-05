"""Multi-store management for PlanoBricks.

Each store has a name, optional description, and its own set of shelf images
and schematic references. Store metadata is persisted as JSON locally and
synced to a UC Volume.

The existing Grocery Dataset images are assigned to "Store A" by default.
Users can create additional stores (Store B, etc.) and upload new shelf
images / schematics for each.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

log = logging.getLogger(__name__)

LOCAL_PATH = os.path.join(os.path.dirname(__file__), "data", "stores.json")
VOLUME_PATH = (
    "/Volumes/serverless_stable_wunnava_catalog"
    "/planobricks_reference/inputs/stores.json"
)

DEFAULT_STORE_ID = "store-a"

_STORES: dict[str, dict] = {}


def _default_store() -> dict:
    return {
        "id": DEFAULT_STORE_ID,
        "name": "Store A",
        "description": "Grocery Dataset — Istanbul tobacco shelf images (Varol & Kuzu, 2014)",
        "created_at": time.time(),
        "image_source": "bundled",
    }


def init():
    """Load stores from disk or create the default store."""
    global _STORES
    saved = _load_from_disk()
    if saved:
        _STORES = saved
    if DEFAULT_STORE_ID not in _STORES:
        _STORES[DEFAULT_STORE_ID] = _default_store()
        _save_to_disk()


def list_stores() -> list[dict]:
    """Return all stores sorted by creation time."""
    return sorted(_STORES.values(), key=lambda s: s.get("created_at", 0))


def get(store_id: str) -> dict | None:
    return _STORES.get(store_id)


def create(name: str, description: str = "") -> dict:
    store_id = f"store-{uuid.uuid4().hex[:8]}"
    store = {
        "id": store_id,
        "name": name,
        "description": description,
        "created_at": time.time(),
        "image_source": "custom",
    }
    _STORES[store_id] = store
    _save_to_disk()
    return store


def update(store_id: str, name: str | None = None, description: str | None = None) -> dict | None:
    store = _STORES.get(store_id)
    if not store:
        return None
    if name is not None:
        store["name"] = name
    if description is not None:
        store["description"] = description
    _save_to_disk()
    return store


def delete(store_id: str) -> bool:
    if store_id == DEFAULT_STORE_ID:
        return False
    if store_id in _STORES:
        del _STORES[store_id]
        _save_to_disk()
        return True
    return False


def _load_from_disk() -> dict[str, dict]:
    for path in [LOCAL_PATH, VOLUME_PATH]:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception as e:
                log.warning("Failed to load stores from %s: %s", path, e)
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


def _save_to_disk():
    os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
    with open(LOCAL_PATH, "w") as f:
        json.dump(_STORES, f, indent=2)
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        content = json.dumps(_STORES, indent=2).encode()
        from io import BytesIO
        w.files.upload(VOLUME_PATH, BytesIO(content), overwrite=True)
    except Exception as e:
        log.warning("Could not save stores to UC Volume: %s", e)
