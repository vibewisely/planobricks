"""Parse the Grocery Dataset annotations and compute planogram compliance.

Data source: https://github.com/gulvarol/grocerydataset
Reference:   Varol & Kuzu, "Toward Retail Product Recognition on Grocery Shelves", ICIVC 2014

Brand identification: all 10,440 "category 0" products were reclassified using
Databricks Foundation Model API (ai_query + Claude Haiku 4.5 vision). Results
merged from enriched_products.csv.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field

ORIGINAL_BRAND_NAMES = {
    0: "Other (Untracked)",
    1: "Marlboro",
    2: "Kent",
    3: "Camel",
    4: "Parliament",
    5: "Pall Mall",
    6: "Monte Carlo",
    7: "Winston",
    8: "Lucky Strike",
    9: "2001",
    10: "Lark",
}

BRAND_COLORS: dict[str, str] = {
    "Marlboro": "#dc2626",
    "Kent": "#2563eb",
    "Camel": "#d97706",
    "Parliament": "#1d4ed8",
    "Pall Mall": "#7c3aed",
    "Monte Carlo": "#059669",
    "Winston": "#ea580c",
    "Lucky Strike": "#e11d48",
    "2001": "#0d9488",
    "Lark": "#4f46e5",
    "Viceroy": "#b45309",
    "Chesterfield": "#65a30d",
    "Davidoff": "#a21caf",
    "West": "#0891b2",
    "L&M": "#c026d3",
    "LD": "#475569",
    "Vogue": "#db2777",
    "Muratti": "#15803d",
    "Bond": "#0369a1",
    "Polo": "#6d28d9",
    "Tekel": "#92400e",
    "Samsun": "#166534",
    "Salem": "#1e3a8a",
    "Dunhill": "#6b21a8",
    "Imperial": "#78716c",
    "Solo": "#9f1239",
    "Bianca": "#831843",
    "Unknown": "#94a3b8",
    "Other": "#cbd5e1",
}

CAMERA_NAMES = {
    "1": "iPhone 5S",
    "2": "iPhone 4",
    "3": "Sony Cybershot",
    "4": "Nikon Coolpix",
}

VOLUME_BASE = "/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images"


@dataclass
class Product:
    x: int
    y: int
    w: int
    h: int
    brand: str

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def center_x(self) -> int:
        return self.x + self.w // 2

    @property
    def center_y(self) -> int:
        return self.y + self.h // 2

    @property
    def color(self) -> str:
        return BRAND_COLORS.get(self.brand, "#94a3b8")


@dataclass
class ShelfImage:
    filename: str
    camera_id: str
    planogram_id: str
    shelf_rank: str
    num_shelves: str
    copy: str
    products: list[Product] = field(default_factory=list)

    @property
    def camera_name(self) -> str:
        return CAMERA_NAMES.get(self.camera_id, f"Camera {self.camera_id}")

    @property
    def num_products(self) -> int:
        return len(self.products)

    @property
    def brand_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.products:
            counts[p.brand] = counts.get(p.brand, 0) + 1
        return counts

    @property
    def identified_count(self) -> int:
        return sum(1 for p in self.products if p.brand not in ("Unknown", "Other"))

    @property
    def identified_pct(self) -> float:
        return self.identified_count / self.num_products * 100 if self.num_products else 0

    @property
    def volume_path(self) -> str:
        return f"{VOLUME_BASE}/ShelfImages/{self.filename}"


def parse_filename(filename: str) -> dict:
    """Parse shelf image filename: C<c>_P<p>_N<n>_S<s>_<i>.JPG"""
    base = filename.replace(".JPG", "").replace(".jpg", "")
    parts = base.split("_")
    return {
        "camera_id": parts[0][1:] if len(parts) > 0 else "0",
        "planogram_id": parts[1][1:] if len(parts) > 1 else "0",
        "shelf_rank": parts[2][1:] if len(parts) > 2 else "0",
        "num_shelves": parts[3][1:] if len(parts) > 3 else "0",
        "copy": parts[4] if len(parts) > 4 else "1",
    }


def _load_enriched_products(data_dir: str) -> dict[tuple[str, int, int], str]:
    """Load enriched_products.csv and return (shelf_image, x, y) → brand mapping."""
    csv_path = os.path.join(data_dir, "enriched_products.csv")
    mapping: dict[tuple[str, int, int], str] = {}
    if not os.path.exists(csv_path):
        return mapping
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["shelf_image"], int(row["bbox_x"]), int(row["bbox_y"]))
            mapping[key] = row["brand"]
    return mapping


def load_annotations(data_dir: str | None = None) -> list[ShelfImage]:
    """Load annotation.txt, enriched with vision-model-identified brands."""
    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(__file__), "data")

    enriched = _load_enriched_products(data_dir)
    ann_path = os.path.join(data_dir, "annotation.txt")
    shelves: list[ShelfImage] = []

    with open(ann_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            filename = parts[0]
            n_products = int(parts[1])
            meta = parse_filename(filename)

            products: list[Product] = []
            idx = 2
            for _ in range(n_products):
                if idx + 5 > len(parts):
                    break
                x = int(parts[idx])
                y = int(parts[idx + 1])
                w = int(parts[idx + 2])
                h = int(parts[idx + 3])
                brand_id = int(parts[idx + 4])
                idx += 5

                if brand_id == 0:
                    brand = enriched.get((filename, x, y), "Unknown")
                else:
                    brand = ORIGINAL_BRAND_NAMES.get(brand_id, "Unknown")

                products.append(Product(x, y, w, h, brand))

            shelves.append(ShelfImage(
                filename=filename,
                camera_id=meta["camera_id"],
                planogram_id=meta["planogram_id"],
                shelf_rank=meta["shelf_rank"],
                num_shelves=meta["num_shelves"],
                copy=meta["copy"],
                products=products,
            ))
    return shelves


# -- Planogram reference generation --

def build_planogram_reference(shelves: list[ShelfImage]) -> dict[str, list[str]]:
    """Build a reference planogram per planogram_id.

    Pick the image with the most products as reference, return brand sequence
    sorted top-to-bottom, left-to-right.
    """
    by_planogram: dict[str, list[ShelfImage]] = {}
    for s in shelves:
        by_planogram.setdefault(s.planogram_id, []).append(s)

    reference: dict[str, list[str]] = {}
    for pid, images in by_planogram.items():
        best = max(images, key=lambda s: s.num_products)
        sorted_products = sorted(best.products, key=lambda p: (p.y, p.x))
        reference[pid] = [p.brand for p in sorted_products]
    return reference


def compute_shelf_compliance(
    shelf: ShelfImage,
    reference: dict[str, list[str]],
) -> dict:
    """Compare a shelf image's detected brands against the planogram reference."""
    ref_brands = reference.get(shelf.planogram_id, [])
    detected_sorted = sorted(shelf.products, key=lambda p: (p.y, p.x))
    detected_brands = [p.brand for p in detected_sorted]

    if not ref_brands:
        return {
            "score": 0.0,
            "correct": 0,
            "incorrect": 0,
            "missing": 0,
            "extra": 0,
            "total_expected": 0,
            "total_detected": len(detected_brands),
            "product_results": [],
        }

    n_ref = len(ref_brands)
    n_det = len(detected_brands)
    correct = 0
    incorrect = 0
    results = []

    for i in range(max(n_ref, n_det)):
        exp = ref_brands[i] if i < n_ref else None
        det = detected_brands[i] if i < n_det else None

        if exp is not None and det is not None:
            if exp == det:
                status = "Correct"
                correct += 1
            elif det in ref_brands:
                status = "Wrong Position"
                incorrect += 1
            else:
                status = "Mismatch"
                incorrect += 1
        elif exp is not None and det is None:
            status = "Out-of-Stock"
        elif exp is None and det is not None:
            status = "Extra"
        else:
            status = "Unknown"

        results.append({
            "position": i + 1,
            "expected_brand": exp or "—",
            "detected_brand": det or "—",
            "status": status,
        })

    missing = max(0, n_ref - n_det)
    extra = max(0, n_det - n_ref)
    score = correct / n_ref if n_ref > 0 else 0.0

    return {
        "score": round(score, 3),
        "correct": correct,
        "incorrect": incorrect,
        "missing": missing,
        "extra": extra,
        "total_expected": n_ref,
        "total_detected": n_det,
        "product_results": results,
    }


# -- Aggregation helpers --

def get_planogram_summary(shelves: list[ShelfImage]) -> list[dict]:
    by_plan: dict[str, list[ShelfImage]] = {}
    for s in shelves:
        by_plan.setdefault(s.planogram_id, []).append(s)

    rows = []
    for pid in sorted(by_plan.keys()):
        images = by_plan[pid]
        total_products = sum(s.num_products for s in images)
        cameras = set(s.camera_id for s in images)
        rows.append({
            "planogram_id": f"P{pid}",
            "num_images": len(images),
            "total_products": total_products,
            "avg_products": round(total_products / len(images), 1),
            "cameras": ", ".join(CAMERA_NAMES.get(c, c) for c in sorted(cameras)),
        })
    return rows


def get_brand_distribution(shelves: list[ShelfImage]) -> list[dict]:
    """Count product instances per brand across all shelves."""
    counts: dict[str, int] = {}
    for s in shelves:
        for brand, cnt in s.brand_counts.items():
            counts[brand] = counts.get(brand, 0) + cnt
    return sorted(
        [
            {"brand": brand, "count": cnt, "color": BRAND_COLORS.get(brand, "#94a3b8")}
            for brand, cnt in counts.items()
        ],
        key=lambda r: r["count"],
        reverse=True,
    )


def get_compliance_overview(shelves: list[ShelfImage], reference: dict[str, list[str]]) -> list[dict]:
    rows = []
    for s in shelves:
        comp = compute_shelf_compliance(s, reference)
        rows.append({
            "filename": s.filename,
            "planogram_id": f"P{s.planogram_id}",
            "camera": s.camera_name,
            "num_shelves": s.num_shelves,
            "num_products": s.num_products,
            "identified_pct": round(s.identified_pct, 0),
            "score": comp["score"],
            "correct": comp["correct"],
            "incorrect": comp["incorrect"],
            "missing": comp["missing"],
            "extra": comp["extra"],
        })
    return rows


# -- Singleton data cache (per-store) --

_CACHE: dict = {}
_STORE_CACHES: dict[str, dict] = {}
_CURRENT_STORE: str = "store-a"


def get_current_store() -> str:
    return _CURRENT_STORE


def set_current_store(store_id: str):
    global _CURRENT_STORE
    _CURRENT_STORE = store_id


def get_data(store_id: str | None = None):
    """Load and cache all parsed data for a store.

    For 'store-a' (default), uses the bundled Grocery Dataset.
    For other stores, returns an empty scaffold (users add schematics via editor).
    """
    if store_id is None:
        store_id = _CURRENT_STORE

    if store_id == "store-a":
        return _get_default_data()

    if store_id not in _STORE_CACHES:
        _STORE_CACHES[store_id] = _build_empty_store_data(store_id)
    return _STORE_CACHES[store_id]


def _get_default_data():
    """Load the bundled Grocery Dataset for Store A."""
    if not _CACHE:
        from planogram_engine import build_schematics, compute_compliance as pe_compliance
        import planogram_store as ps

        shelves = load_annotations()
        reference = build_planogram_reference(shelves)
        auto_schematics = build_schematics(shelves)

        ps.init_from_auto(auto_schematics)

        schematics = _resolve_schematics(ps)

        compliance_results = {}
        for s in shelves:
            compliance_results[s.filename] = pe_compliance(s, schematics)

        _CACHE["shelves"] = shelves
        _CACHE["shelf_map"] = {s.filename: s for s in shelves}
        _CACHE["reference"] = reference
        _CACHE["schematics"] = schematics
        _CACHE["compliance_results"] = compliance_results
        _CACHE["planogram_summary"] = get_planogram_summary(shelves)
        _CACHE["brand_distribution"] = get_brand_distribution(shelves)
        _CACHE["compliance_overview"] = _build_compliance_overview(shelves, compliance_results)
    return _CACHE


def _build_empty_store_data(store_id: str):
    """Build data scaffold for a non-default store, loading registered images."""
    from planogram_engine import SchematicKey, compute_compliance as pe_compliance

    import planogram_store as ps
    import store_images as si

    store_schematics_raw = ps.load_store_schematics(store_id)
    schematics: dict[SchematicKey, any] = {}
    for ks, d in store_schematics_raw.items():
        sp = ps.dict_to_schematic(d)
        key = (sp.planogram_id, sp.num_shelves, sp.shelf_rank)
        schematics[key] = sp

    # Load registered shelf images (uploaded via email or other sources)
    shelves = si.manifest_to_shelf_images(store_id)

    # Compute compliance for registered images against store schematics
    compliance_results = {}
    for s in shelves:
        compliance_results[s.filename] = pe_compliance(s, schematics)

    return {
        "shelves": shelves,
        "shelf_map": {s.filename: s for s in shelves},
        "reference": {},
        "schematics": schematics,
        "compliance_results": compliance_results,
        "planogram_summary": get_planogram_summary(shelves) if shelves else [],
        "brand_distribution": get_brand_distribution(shelves) if shelves else [],
        "compliance_overview": (
            _build_compliance_overview(shelves, compliance_results) if shelves else []
        ),
        "store_schematics_raw": store_schematics_raw,
    }


def refresh_compliance(store_id: str | None = None):
    """Recompute compliance after schematic edits. Call after saving schematics."""
    if store_id is None:
        store_id = _CURRENT_STORE

    if store_id == "store-a":
        _refresh_default_compliance()
    else:
        if store_id in _STORE_CACHES:
            del _STORE_CACHES[store_id]


def _refresh_default_compliance():
    if not _CACHE:
        return

    from planogram_engine import compute_compliance as pe_compliance
    import planogram_store as ps

    schematics = _resolve_schematics(ps)
    shelves = _CACHE["shelves"]

    compliance_results = {}
    for s in shelves:
        compliance_results[s.filename] = pe_compliance(s, schematics)

    _CACHE["schematics"] = schematics
    _CACHE["compliance_results"] = compliance_results
    _CACHE["compliance_overview"] = _build_compliance_overview(shelves, compliance_results)


def _resolve_schematics(ps):
    """Build the schematics dict from the store (includes custom overrides)."""
    from planogram_engine import SchematicKey
    schematics: dict[SchematicKey, any] = {}
    for ks, d in ps.get_all().items():
        sp = ps.dict_to_schematic(d)
        key = (sp.planogram_id, sp.num_shelves, sp.shelf_rank)
        schematics[key] = sp
    return schematics


def _build_compliance_overview(shelves, compliance_results):
    rows = []
    for s in shelves:
        cr = compliance_results[s.filename]
        rows.append({
            "filename": s.filename,
            "planogram_id": f"P{s.planogram_id}",
            "camera": s.camera_name,
            "num_shelves": s.num_shelves,
            "num_products": s.num_products,
            "identified_pct": round(s.identified_pct, 0),
            "score": cr.score,
            "correct": cr.correct,
            "wrong_position": cr.wrong_position,
            "substitution": cr.substitution,
            "out_of_stock": cr.out_of_stock,
            "extra": cr.extra,
        })
    return rows
