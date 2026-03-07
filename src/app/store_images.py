"""Per-store shelf image registry.

Stores a JSON manifest of registered shelf images per store, with
local file + UC Volume dual-persistence (same pattern as planogram_store.py).

Each store's manifest is a dict keyed by filename:
{
  "shelf_001.jpg": {
    "filename": "shelf_001.jpg",
    "camera_id": "email",
    "planogram_id": "10",
    "num_shelves": "3",
    "shelf_rank": "1",
    "copy": "1",
    "products": [{"x": 10, "y": 20, "w": 50, "h": 80, "brand": "Marlboro"}, ...],
    "source": "email",
    "registered_at": 1741190400.0,
    "volume_path": "/Volumes/.../store_images/{store_id}/shelf_001.jpg"
  }
}
"""

from __future__ import annotations

import json
import logging
import os
import time

from grocery_data import Product, ShelfImage

log = logging.getLogger(__name__)

STORE_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "data", "store_images")
VOLUME_BASE = (
    "/Volumes/serverless_stable_wunnava_catalog"
    "/planobricks_reference/inputs"
)


def _local_path(store_id: str) -> str:
    return os.path.join(STORE_IMAGES_DIR, f"{store_id}.json")


def _volume_manifest_path(store_id: str) -> str:
    return f"{VOLUME_BASE}/store_images_{store_id}.json"


def store_image_volume_dir(store_id: str) -> str:
    """UC Volume directory for a store's shelf images."""
    return f"{VOLUME_BASE}/images/store_images/{store_id}"


# ─── Load / Save (dual persistence) ────────────────────────────

def load_manifest(store_id: str) -> dict[str, dict]:
    """Load the image manifest for a store. Tries local, then UC Volume."""
    local = _local_path(store_id)
    if os.path.isfile(local):
        try:
            with open(local) as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to load image manifest from %s: %s", local, e)

    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        resp = w.files.download(_volume_manifest_path(store_id))
        data = json.loads(resp.contents.read())
        os.makedirs(STORE_IMAGES_DIR, exist_ok=True)
        with open(local, "w") as f:
            json.dump(data, f)
        return data
    except Exception:
        pass

    return {}


def save_manifest(store_id: str, manifest: dict[str, dict]) -> None:
    """Persist manifest to local file + UC Volume."""
    os.makedirs(STORE_IMAGES_DIR, exist_ok=True)
    local = _local_path(store_id)
    with open(local, "w") as f:
        json.dump(manifest, f, indent=2)

    try:
        from io import BytesIO

        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        content = json.dumps(manifest, indent=2).encode()
        w.files.upload(_volume_manifest_path(store_id), BytesIO(content), overwrite=True)
        log.info("Image manifest saved to UC Volume for %s", store_id)
    except Exception as e:
        log.warning("Could not save image manifest to UC Volume: %s", e)


# ─── CRUD ───────────────────────────────────────────────────────

def register_image(
    store_id: str,
    filename: str,
    planogram_id: str,
    num_shelves: str,
    shelf_rank: str,
    products: list[dict],
    source: str = "email",
    email_subject: str = "",
    email_message_id: str = "",
) -> dict:
    """Register a single image in the store manifest. Returns the entry."""
    manifest = load_manifest(store_id)
    volume_path = f"{store_image_volume_dir(store_id)}/{filename}"
    entry = {
        "filename": filename,
        "camera_id": source,
        "planogram_id": planogram_id,
        "num_shelves": num_shelves,
        "shelf_rank": shelf_rank,
        "copy": "1",
        "products": products,
        "source": source,
        "email_subject": email_subject,
        "email_message_id": email_message_id,
        "registered_at": time.time(),
        "volume_path": volume_path,
    }
    manifest[filename] = entry
    save_manifest(store_id, manifest)
    return entry


def list_images(store_id: str) -> list[dict]:
    """Return all registered images for a store, sorted by registration time."""
    manifest = load_manifest(store_id)
    return sorted(manifest.values(), key=lambda e: e.get("registered_at", 0))


def delete_image(store_id: str, filename: str) -> bool:
    """Remove an image from the manifest."""
    manifest = load_manifest(store_id)
    if filename in manifest:
        del manifest[filename]
        save_manifest(store_id, manifest)
        return True
    return False


# ─── Conversion ─────────────────────────────────────────────────

def manifest_to_shelf_images(store_id: str) -> list[ShelfImage]:
    """Convert the manifest into a list of ShelfImage dataclass instances."""
    manifest = load_manifest(store_id)
    shelves = []
    for entry in sorted(manifest.values(), key=lambda e: e.get("registered_at", 0)):
        products = [
            Product(x=p["x"], y=p["y"], w=p["w"], h=p["h"], brand=p["brand"])
            for p in entry.get("products", [])
        ]
        shelves.append(
            ShelfImage(
                filename=entry["filename"],
                camera_id=entry.get("camera_id", "email"),
                planogram_id=entry.get("planogram_id", "0"),
                shelf_rank=entry.get("shelf_rank", "0"),
                num_shelves=entry.get("num_shelves", "0"),
                copy=entry.get("copy", "1"),
                products=products,
            )
        )
    return shelves


# ─── Volume upload ──────────────────────────────────────────────

def upload_image_to_volume(store_id: str, filename: str, image_bytes: bytes) -> str:
    """Upload image bytes to UC Volume at the store-scoped path.

    Returns the full volume path.
    """
    volume_path = f"{store_image_volume_dir(store_id)}/{filename}"
    try:
        from io import BytesIO

        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        w.files.upload(volume_path, BytesIO(image_bytes), overwrite=True)
        print(f"[StoreImages] Uploaded {filename} to {volume_path}", flush=True)
    except Exception as e:
        print(f"[StoreImages] Failed to upload {filename}: {e}", flush=True)
        # Also save locally as fallback
        cache_dir = os.path.join(STORE_IMAGES_DIR, "cache", store_id)
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, filename), "wb") as f:
            f.write(image_bytes)
        print(f"[StoreImages] Saved locally to {cache_dir}/{filename}", flush=True)
    return volume_path
