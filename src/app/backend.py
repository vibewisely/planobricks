"""Data backend with mock data and real Databricks SQL backend."""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta

CATALOG = os.getenv("DATABRICKS_CATALOG", "serverless_stable_wunnava_catalog")

STORES = [
    {"store_id": "S001", "store_name": "Plano Market Street", "region": "North Texas", "district": "Plano", "format": "Supermarket", "latitude": 33.0198, "longitude": -96.6989},
    {"store_id": "S002", "store_name": "Frisco Town Center", "region": "North Texas", "district": "Frisco", "format": "Supermarket", "latitude": 33.1507, "longitude": -96.8236},
    {"store_id": "S003", "store_name": "Allen Gateway", "region": "North Texas", "district": "Allen", "format": "Convenience", "latitude": 33.1032, "longitude": -96.6706},
    {"store_id": "S004", "store_name": "McKinney Square", "region": "North Texas", "district": "McKinney", "format": "Supermarket", "latitude": 33.1972, "longitude": -96.6397},
    {"store_id": "S005", "store_name": "Richardson Heights", "region": "North Texas", "district": "Richardson", "format": "Warehouse", "latitude": 32.9483, "longitude": -96.7299},
    {"store_id": "S006", "store_name": "Dallas Uptown", "region": "North Texas", "district": "Dallas", "format": "Convenience", "latitude": 32.7996, "longitude": -96.8017},
    {"store_id": "S007", "store_name": "Fort Worth Stockyards", "region": "West Texas", "district": "Fort Worth", "format": "Supermarket", "latitude": 32.7904, "longitude": -97.3471},
    {"store_id": "S008", "store_name": "Arlington Parks", "region": "West Texas", "district": "Arlington", "format": "Supermarket", "latitude": 32.7357, "longitude": -97.1081},
    {"store_id": "S009", "store_name": "Denton University", "region": "North Texas", "district": "Denton", "format": "Convenience", "latitude": 33.2148, "longitude": -97.1331},
    {"store_id": "S010", "store_name": "Prosper Commons", "region": "North Texas", "district": "Prosper", "format": "Supermarket", "latitude": 33.2362, "longitude": -96.8011},
]

PRODUCTS = [
    {"sku_id": "SKU_001", "product_name": "Cola Classic 12oz", "brand": "CocaCola", "category": "Beverages", "package_type": "Can"},
    {"sku_id": "SKU_002", "product_name": "Diet Cola 12oz", "brand": "CocaCola", "category": "Beverages", "package_type": "Can"},
    {"sku_id": "SKU_003", "product_name": "Lemon Lime 12oz", "brand": "Sprite", "category": "Beverages", "package_type": "Can"},
    {"sku_id": "SKU_004", "product_name": "Orange Soda 12oz", "brand": "Fanta", "category": "Beverages", "package_type": "Can"},
    {"sku_id": "SKU_005", "product_name": "Root Beer 12oz", "brand": "A&W", "category": "Beverages", "package_type": "Can"},
    {"sku_id": "SKU_006", "product_name": "Potato Chips Original", "brand": "Lays", "category": "Snacks", "package_type": "Bag"},
    {"sku_id": "SKU_007", "product_name": "BBQ Chips", "brand": "Lays", "category": "Snacks", "package_type": "Bag"},
    {"sku_id": "SKU_008", "product_name": "Tortilla Chips", "brand": "Doritos", "category": "Snacks", "package_type": "Bag"},
    {"sku_id": "SKU_009", "product_name": "Cheese Puffs", "brand": "Cheetos", "category": "Snacks", "package_type": "Bag"},
    {"sku_id": "SKU_010", "product_name": "Pretzels Mini", "brand": "Rold Gold", "category": "Snacks", "package_type": "Bag"},
    {"sku_id": "SKU_011", "product_name": "Whole Milk 1gal", "brand": "Horizon", "category": "Dairy", "package_type": "Bottle"},
    {"sku_id": "SKU_012", "product_name": "2% Milk 1gal", "brand": "Horizon", "category": "Dairy", "package_type": "Bottle"},
    {"sku_id": "SKU_013", "product_name": "Greek Yogurt Plain", "brand": "Chobani", "category": "Dairy", "package_type": "Cup"},
    {"sku_id": "SKU_014", "product_name": "Greek Yogurt Strawberry", "brand": "Chobani", "category": "Dairy", "package_type": "Cup"},
    {"sku_id": "SKU_015", "product_name": "Cheddar Cheese Block", "brand": "Tillamook", "category": "Dairy", "package_type": "Block"},
    {"sku_id": "SKU_016", "product_name": "Wheat Bread", "brand": "Natures Own", "category": "Bakery", "package_type": "Bag"},
    {"sku_id": "SKU_017", "product_name": "White Bread", "brand": "Wonder", "category": "Bakery", "package_type": "Bag"},
    {"sku_id": "SKU_018", "product_name": "Peanut Butter Creamy", "brand": "Jif", "category": "Pantry", "package_type": "Jar"},
    {"sku_id": "SKU_019", "product_name": "Grape Jelly", "brand": "Smuckers", "category": "Pantry", "package_type": "Jar"},
    {"sku_id": "SKU_020", "product_name": "Pasta Spaghetti", "brand": "Barilla", "category": "Pantry", "package_type": "Box"},
]

SKU_MAP = {p["sku_id"]: p for p in PRODUCTS}


def _seed_rng(store_id: str, day: date) -> random.Random:
    return random.Random(f"{store_id}-{day.isoformat()}")


def generate_daily_compliance(store: dict, day: date) -> dict:
    """Generate deterministic mock compliance data for a store+day."""
    rng = _seed_rng(store["store_id"], day)
    base_score = 0.65 + rng.random() * 0.30
    if store["format"] == "Warehouse":
        base_score = min(base_score + 0.05, 1.0)
    if store["format"] == "Convenience":
        base_score = max(base_score - 0.05, 0.0)

    total = rng.randint(30, 60)
    correct = int(total * base_score)
    remaining = total - correct
    incorrect_pos = int(remaining * 0.3)
    oos = int(remaining * 0.4)
    extra = remaining - incorrect_pos - oos

    categories = ["Beverages", "Snacks", "Dairy", "Bakery", "Pantry"]
    worst_cat = rng.choice(categories)
    worst_shelf = f"Shelf {rng.randint(1, 5)}"

    return {
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "region": store["region"],
        "district": store["district"],
        "format": store["format"],
        "date": day.isoformat(),
        "overall_score": round(base_score, 3),
        "num_audits": rng.randint(1, 3),
        "num_shelves_audited": rng.randint(8, 20),
        "correct_count": correct,
        "incorrect_position_count": incorrect_pos,
        "out_of_stock_count": oos,
        "extra_product_count": extra,
        "unknown_count": rng.randint(0, 3),
        "worst_shelf": worst_shelf,
        "worst_category": worst_cat,
    }


def get_stores() -> list[dict]:
    return STORES


def get_products() -> list[dict]:
    return PRODUCTS


def get_store_compliance_today(store_id: str | None = None) -> list[dict]:
    today = date.today()
    stores = [s for s in STORES if s["store_id"] == store_id] if store_id else STORES
    return [generate_daily_compliance(s, today) for s in stores]


def get_compliance_trends(store_id: str, days: int = 30) -> list[dict]:
    store = next((s for s in STORES if s["store_id"] == store_id), STORES[0])
    today = date.today()
    return [generate_daily_compliance(store, today - timedelta(days=i)) for i in range(days - 1, -1, -1)]


def get_portfolio_kpis() -> dict:
    today = date.today()
    records = [generate_daily_compliance(s, today) for s in STORES]
    scores = [r["overall_score"] for r in records]
    total_oos = sum(r["out_of_stock_count"] for r in records)
    below_threshold = sum(1 for s in scores if s < 0.80)
    return {
        "avg_score": round(sum(scores) / len(scores), 3),
        "total_stores": len(STORES),
        "audits_today": sum(r["num_audits"] for r in records),
        "stores_below_threshold": below_threshold,
        "total_oos": total_oos,
    }


def get_shelf_heatmap(store_id: str) -> list[dict]:
    """Generate shelf-level heatmap data for a store."""
    rng = _seed_rng(store_id, date.today())
    statuses = ["Correct", "Incorrect Position", "Out-of-Stock", "Extra Product"]
    weights = [0.70, 0.10, 0.12, 0.08]
    rows = []
    for shelf in range(1, 6):
        for pos in range(1, 9):
            sku = rng.choice(PRODUCTS)
            status = rng.choices(statuses, weights=weights, k=1)[0]
            rows.append({
                "shelf_row": shelf,
                "position": pos,
                "expected_sku": sku["sku_id"],
                "detected_sku": sku["sku_id"] if status == "Correct" else rng.choice(PRODUCTS)["sku_id"],
                "status": status,
                "product_name": sku["product_name"],
                "confidence": round(rng.uniform(0.60, 0.99), 2),
            })
    return rows


def get_deviation_summary() -> list[dict]:
    """Aggregate deviation types across all stores."""
    today = date.today()
    records = [generate_daily_compliance(s, today) for s in STORES]
    return [
        {"type": "Correct", "count": sum(r["correct_count"] for r in records), "color": "#22c55e"},
        {"type": "Incorrect Position", "count": sum(r["incorrect_position_count"] for r in records), "color": "#eab308"},
        {"type": "Out-of-Stock", "count": sum(r["out_of_stock_count"] for r in records), "color": "#ef4444"},
        {"type": "Extra Product", "count": sum(r["extra_product_count"] for r in records), "color": "#f97316"},
        {"type": "Unknown", "count": sum(r["unknown_count"] for r in records), "color": "#6b7280"},
    ]
