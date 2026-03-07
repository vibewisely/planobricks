#!/usr/bin/env python3
"""Email-to-Shelf: Fetch shelf images from Gmail and register in PlanoBricks.

Searches Gmail for unread emails with subject matching "planobricks: <Store> <SchematicKey>",
downloads image attachments, uploads to UC Volume, runs AI brand detection via FMAPI
(Claude Haiku 4.5), and registers in the per-store image manifest.

Prerequisites:
    - Gmail auth: gcloud auth application-default login
    - Databricks auth: profile 'planobricks-mar2' configured

Usage:
    python scripts/email_to_shelf.py                     # Process all unread
    python scripts/email_to_shelf.py --dry-run            # Preview without processing
    python scripts/email_to_shelf.py --query "subject:planobricks newer_than:1d"
"""

from __future__ import annotations

import argparse
import base64
import glob
import os
import re
import sys
import tempfile
import time

# ─── Path setup ─────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(SCRIPT_DIR, "..", "src", "app")
sys.path.insert(0, APP_DIR)

# Gmail skill resources — find the installed version dynamically
_GMAIL_PLUGIN_BASE = os.path.expanduser(
    "~/.claude/plugins/cache/fe-vibe/fe-google-tools"
)
_gmail_versions = sorted(glob.glob(os.path.join(_GMAIL_PLUGIN_BASE, "*")))
if _gmail_versions:
    _latest = _gmail_versions[-1]
    sys.path.insert(0, os.path.join(_latest, "skills", "gmail", "resources"))
    sys.path.insert(0, os.path.join(_latest, "skills", "google-auth", "resources"))


# ─── Subject line parsing ───────────────────────────────────────


def parse_subject(subject: str) -> tuple[str | None, str | None]:
    """Parse email subject for store name and optional schematic key.

    Returns (store_name, schematic_key) or (None, None).

    Examples:
        "planobricks: Store B"           -> ("Store B", None)
        "planobricks: Store B P10/3s/R1" -> ("Store B", "P10/3s/R1")
        "shelf: My Store P01/2s/R1"      -> ("My Store", "P01/2s/R1")
    """
    pattern = r"(?:planobricks|shelf)\s*:\s*(.+)"
    match = re.match(pattern, subject, re.IGNORECASE)
    if not match:
        return None, None

    remainder = match.group(1).strip()

    # Try to extract schematic key (P<id>/<n>s/R<r>)
    key_pattern = r"\b(P\d+/\d+s/R\d+)\s*$"
    key_match = re.search(key_pattern, remainder)

    if key_match:
        schematic_key = key_match.group(1)
        store_name = remainder[: key_match.start()].strip()
    else:
        schematic_key = None
        store_name = remainder

    return store_name or None, schematic_key


def resolve_store_id(store_name: str) -> str | None:
    """Find store ID by name match (case-insensitive)."""
    import store_manager as sm

    sm.init()
    for store in sm.list_stores():
        if store["name"].lower() == store_name.lower():
            return store["id"]
    return None


# ─── AI brand detection ─────────────────────────────────────────


def detect_brands_from_image_bytes(
    image_bytes: bytes, num_rows: int | None = None
) -> tuple[list[list[str]], int]:
    """Call FMAPI to detect brands from raw image bytes.

    If num_rows is None, asks the AI to auto-detect the number of shelf rows.
    Returns (list of brand rows, detected_num_rows).
    """
    from databricks.sdk import WorkspaceClient

    b64_data = base64.b64encode(image_bytes).decode()

    if num_rows is None:
        prompt = (
            "Analyze this shelf image. First, determine how many horizontal shelf rows "
            "are visible. Then identify ALL product brands visible on each shelf row, "
            "from top to bottom.\n\n"
            "Return your answer in this EXACT format:\n"
            "ROWS: <number>\n"
            "Row 1: Brand1 | Brand2 | Brand3\n"
            "Row 2: Brand4 | Brand5\n"
            "...\n\n"
            "If you cannot identify a brand, use 'Unknown'. "
            "List brands left to right, separated by pipe (|)."
        )
    else:
        prompt = (
            f"Analyze this shelf image. Identify ALL product brands visible on the shelves, "
            f"organized into {num_rows} shelf rows from top to bottom. "
            f"For each row, list brands left to right separated by pipe (|). "
            f"Return ONLY the brand names, one row per line, using | as separator. "
            f"If you cannot identify a brand, use 'Unknown'."
        )

    w = WorkspaceClient(profile="planobricks-mar2")
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"},
                    },
                ],
            }
        ],
        "max_tokens": 1024,
    }

    try:
        print("  [AI] Calling FMAPI (Claude Haiku 4.5)...", flush=True)
        resp = w.api_client.do(
            "POST",
            "/serving-endpoints/databricks-claude-haiku-4-5/invocations",
            body=payload,
        )

        text = ""
        if isinstance(resp, dict):
            choices = resp.get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "")

        print(f"  [AI] Response ({len(text)} chars): {text[:200]}", flush=True)

        if text:
            rows, detected_rows = _parse_brand_response(text, num_rows)
            return rows, detected_rows

    except Exception as e:
        print(f"  [AI] FMAPI call failed: {type(e).__name__}: {e}", flush=True)

    # Fallback
    fallback_rows = num_rows or 3
    return [["Unknown"] * 5 for _ in range(fallback_rows)], fallback_rows


def _parse_brand_response(
    text: str, num_rows: int | None
) -> tuple[list[list[str]], int]:
    """Parse AI model response into rows of brand names.

    Handles two formats:
    1. Auto-detect: "ROWS: 3\nRow 1: A | B | C\n..."
    2. Simple: "A | B | C\nD | E | F"

    Returns (brand_rows, detected_num_rows).
    """
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]

    # Try to extract ROWS: N header
    detected_rows = num_rows
    for line in lines:
        rows_match = re.match(r"ROWS?\s*:\s*(\d+)", line, re.IGNORECASE)
        if rows_match:
            detected_rows = int(rows_match.group(1))
            break

    # Extract brand rows (lines containing |)
    rows = []
    for line in lines:
        # Strip "Row N:" prefix if present
        cleaned = re.sub(r"^Row\s*\d+\s*:\s*", "", line, flags=re.IGNORECASE)
        if "|" in cleaned:
            brands = [b.strip() for b in cleaned.split("|") if b.strip()]
            if brands:
                rows.append(brands)

    if not rows:
        # Fallback: split by commas
        words = [w.strip() for w in text.replace(",", "|").split("|") if w.strip()]
        fallback_n = detected_rows or 3
        if words:
            per_row = max(1, len(words) // fallback_n)
            for i in range(fallback_n):
                start = i * per_row
                end = start + per_row if i < fallback_n - 1 else len(words)
                rows.append(words[start:end] if start < len(words) else ["Unknown"])

    if detected_rows is None:
        detected_rows = len(rows) if rows else 3

    # Pad or trim to detected_rows
    while len(rows) < detected_rows:
        rows.append(["Unknown"] * 5)
    if len(rows) > detected_rows:
        rows = rows[:detected_rows]

    return rows, detected_rows


# ─── Synthetic bounding boxes ───────────────────────────────────


def brands_to_products(
    brand_rows: list[list[str]], img_width: int = 800, img_height: int = 600
) -> list[dict]:
    """Generate synthetic bounding boxes from brand rows.

    Creates evenly-spaced product boxes for each row. Sufficient for
    compliance computation (which only uses brand sequences).
    """
    products = []
    n_rows = max(len(brand_rows), 1)
    row_height = img_height // n_rows

    for row_idx, brands in enumerate(brand_rows):
        if not brands:
            continue
        y = row_idx * row_height + 10
        h = row_height - 20
        col_width = img_width // max(len(brands), 1)

        for col_idx, brand in enumerate(brands):
            x = col_idx * col_width + 5
            w = col_width - 10
            products.append({"x": x, "y": y, "w": w, "h": h, "brand": brand})

    return products


# ─── Email processing ───────────────────────────────────────────


def process_email(message_id: str, subject: str, dry_run: bool = False) -> dict:
    """Process a single email: download attachment, upload to volume, register."""
    import store_images as si

    store_name, schematic_key = parse_subject(subject)
    if not store_name:
        return {"status": "skipped", "reason": f"Could not parse store name from: {subject}"}

    store_id = resolve_store_id(store_name)
    if not store_id:
        return {
            "status": "skipped",
            "reason": f"No store found matching '{store_name}'. Create it in the app first.",
        }

    if dry_run:
        return {
            "status": "dry_run",
            "store_name": store_name,
            "store_id": store_id,
            "schematic_key": schematic_key,
        }

    # Import Gmail functions
    from gmail_builder import download_attachments, modify_labels

    # Download attachments to temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded = download_attachments(message_id, tmpdir)

        # Filter for image files
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        image_files = [
            f for f in downloaded if os.path.splitext(f)[1].lower() in image_exts
        ]

        if not image_files:
            return {"status": "skipped", "reason": "No image attachments found"}

        # Parse schematic key for metadata
        if schematic_key:
            from planogram_store import _key_tuple

            kt = _key_tuple(schematic_key)
            pid, ns, sr = kt
        else:
            pid, ns, sr = "0", "3", "1"

        results = []
        for image_path in image_files:
            original_name = os.path.basename(image_path)
            # Add timestamp prefix to avoid filename collisions
            ts = int(time.time())
            filename = f"{ts}_{original_name}"

            with open(image_path, "rb") as f:
                image_bytes = f.read()

            print(f"  Uploading {filename} to UC Volume...", flush=True)
            volume_path = si.upload_image_to_volume(store_id, filename, image_bytes)

            # AI brand detection (auto-detect row count)
            num_rows_hint = int(ns) if ns.isdigit() and schematic_key else None
            row_label = "auto" if num_rows_hint is None else num_rows_hint
            print(f"  [AI] Detecting brands (rows={row_label})...", flush=True)
            brand_rows, detected_rows = detect_brands_from_image_bytes(
                image_bytes, num_rows_hint
            )

            # Update num_shelves if auto-detected
            actual_ns = str(detected_rows)

            # Generate synthetic bounding boxes
            products = brands_to_products(brand_rows)

            # Register image in manifest
            si.register_image(
                store_id=store_id,
                filename=filename,
                planogram_id=pid,
                num_shelves=actual_ns,
                shelf_rank=sr,
                products=products,
                source="email",
                email_subject=subject,
                email_message_id=message_id,
            )

            # Also create/update a schematic from the detected brands
            import planogram_engine as pe
            import planogram_store as ps

            actual_key = schematic_key or f"P{pid}/{actual_ns}s/R{sr}"
            schem_rows = [
                pe.SchematicRow(row_index=i, brands=row_brands)
                for i, row_brands in enumerate(brand_rows)
            ]
            sp = pe.SchematicPlanogram(
                planogram_id=pid,
                num_shelves=actual_ns,
                shelf_rank=sr,
                rows=schem_rows,
                source_images=[filename],
            )
            ps.save_for_store(
                store_id, actual_key, sp,
                origin="custom",
                source_image_path=volume_path,
                created_by="email_to_shelf",
            )
            print(f"  Schematic {actual_key} saved to store + Delta", flush=True)

            total_brands = sum(len(r) for r in brand_rows)
            results.append(
                {
                    "filename": filename,
                    "volume_path": volume_path,
                    "brands_detected": total_brands,
                    "num_rows": detected_rows,
                    "schematic_key": schematic_key or f"P{pid}/{actual_ns}s/R{sr}",
                }
            )

        # Mark email as read
        try:
            modify_labels(message_id, remove_labels=["UNREAD"])
            print("  Marked email as read", flush=True)
        except Exception as e:
            print(f"  Warning: could not mark as read: {e}", flush=True)

        return {
            "status": "processed",
            "store_name": store_name,
            "store_id": store_id,
            "images": results,
        }


# ─── Main ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Email-to-Shelf processor for PlanoBricks"
    )
    parser.add_argument(
        "--query",
        default="subject:planobricks is:unread has:attachment",
        help="Gmail search query (default: unread planobricks emails with attachments)",
    )
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be processed"
    )
    args = parser.parse_args()

    from gmail_builder import search_messages

    print(f"Searching Gmail: {args.query}")
    messages = search_messages(args.query, args.max_results)
    print(f"Found {len(messages)} matching email(s)\n")

    if not messages:
        print("No matching emails. Send a photo with subject like:")
        print('  "planobricks: Store B P10/3s/R1"')
        return

    processed_stores = set()
    for msg in messages:
        subject = msg.get("subject", "")
        msg_id = msg["id"]
        sender = msg.get("from", "unknown")
        print(f"{'[DRY RUN] ' if args.dry_run else ''}Email: {subject}")
        print(f"  From: {sender}, Date: {msg.get('date', 'unknown')}")

        result = process_email(msg_id, subject, dry_run=args.dry_run)
        print(f"  Result: {result['status']}")

        if result["status"] == "processed":
            for img in result.get("images", []):
                print(f"    -> {img['filename']}: {img['brands_detected']} brands, "
                      f"{img['num_rows']} rows")
            processed_stores.add(result["store_id"])
        elif result["status"] == "skipped":
            print(f"    Reason: {result['reason']}")
        elif result["status"] == "dry_run":
            print(f"    Would process for: {result['store_name']} ({result['store_id']})")
            if result.get("schematic_key"):
                print(f"    Schematic key: {result['schematic_key']}")

        print()

    if processed_stores and not args.dry_run:
        # Invalidate caches so next app load picks up new images
        import grocery_data as gd

        for sid in processed_stores:
            gd.refresh_compliance(sid)
            print(f"Refreshed compliance cache for {sid}")

        print("\nDone! Switch to the store in the app to see new images.")


if __name__ == "__main__":
    main()
