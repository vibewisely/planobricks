#!/usr/bin/env python3
"""Verify Shelf Inspector tab: crop slider and Preview Compliance.

1. Navigate to PlanoBricks app
2. Click Shelf Inspector tab
3. Wait for shelf image to load
4. Screenshot: look for crop slider below Schematic Reference, Preview Compliance card
5. If crop slider visible: drag to [3, 10]
6. Screenshot: cropped state (dimmed columns, UNCOMMITTED badge, Commit/Reset buttons)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright not installed. Run: uv add --dev playwright")
    print("Then: uv run playwright install chromium")
    sys.exit(1)

URL = "https://planobricks-dev-7474651516019640.aws.databricksapps.com"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "dashboard_screenshots"


def run_verification(headless: bool = False) -> dict:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "url": URL,
        "page_load_ok": False,
        "login_redirected": False,
        "shelf_inspector_loaded": False,
        "crop_slider_visible": False,
        "preview_compliance_visible": False,
        "crop_applied": False,
        "uncommitted_badge_visible": False,
        "commit_reset_buttons_visible": False,
        "screenshots": [],
        "errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()

        try:
            # 1. Navigate
            print(f"Navigating to {URL}...")
            response = page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            if response and response.status >= 400:
                report["errors"].append(f"HTTP {response.status}")
                return report

            # Check login redirect
            if "login" in page.url.lower() or "accounts.databricks" in page.url:
                report["login_redirected"] = True
                if not headless:
                    print("Login detected. Please log in. Waiting up to 90s...")
                    try:
                        page.wait_for_url(re.compile(r"databricksapps\.com"), timeout=90000)
                        report["login_redirected"] = False
                        report["page_load_ok"] = True
                        page.wait_for_timeout(5000)
                        page.wait_for_selector(".navbar, #main-tabs, [role='tab']", timeout=15000)
                    except Exception:
                        report["errors"].append("Timed out waiting for login")
                        page.screenshot(path=SCREENSHOTS_DIR / "00_login_redirect.png")
                        report["screenshots"].append("00_login_redirect.png")
                        browser.close()
                        return report
                else:
                    report["errors"].append("Redirected to login - run without --headless to log in")
                    page.screenshot(path=SCREENSHOTS_DIR / "00_login_redirect.png")
                    report["screenshots"].append("00_login_redirect.png")
                    browser.close()
                    return report
            else:
                report["page_load_ok"] = True

            # 2. Click Shelf Inspector tab
            print("Clicking Shelf Inspector tab...")
            shelf_tab = page.locator('text="Shelf Inspector"').first
            if shelf_tab.count() == 0:
                shelf_tab = page.locator('[role="tab"]:has-text("Shelf Inspector")').first
            if shelf_tab.count() == 0:
                shelf_tab = page.locator('.nav-link:has-text("Shelf Inspector")').first
            if shelf_tab.count() == 0:
                report["errors"].append("Shelf Inspector tab not found")
                page.screenshot(path=SCREENSHOTS_DIR / "99_error.png")
                report["screenshots"].append("99_error.png")
                browser.close()
                return report

            shelf_tab.click()
            page.wait_for_timeout(4000)  # Wait for shelf image and schematic to load

            report["shelf_inspector_loaded"] = True

            # 3. Check for crop slider and Preview Compliance
            crop_label = page.locator('text="Crop: select column range to compare"')
            crop_slider = page.locator("#crop-range-slider")
            crop_container = page.locator("#crop-slider-container")
            preview_card = page.locator('text="Preview Compliance"')
            preview_badge = page.locator("#preview-badge")
            commit_btn = page.locator("#commit-crop-btn")
            reset_btn = page.locator("#reset-crop-btn")

            # Crop slider visible when container is shown (schematic has >1 column)
            report["crop_slider_visible"] = crop_label.count() > 0 and crop_slider.count() > 0
            if crop_container.count() > 0:
                try:
                    display = crop_container.first.evaluate("el => window.getComputedStyle(el).display")
                    report["crop_slider_visible"] = report["crop_slider_visible"] and (display != "none")
                except Exception:
                    pass

            report["preview_compliance_visible"] = preview_card.count() > 0

            # Screenshot 1: full Shelf Inspector (initial)
            print("Screenshot 1: Shelf Inspector (full tab)...")
            page.screenshot(path=SCREENSHOTS_DIR / "shelf_inspector_full_initial.png", full_page=True)
            report["screenshots"].append("shelf_inspector_full_initial.png")

            # 4. If crop slider visible, drag to [3, 10]
            if report["crop_slider_visible"] and crop_slider.count() > 0:
                print("Crop slider visible. Dragging to range [3, 10]...")
                try:
                    # Dash RangeSlider: rc-slider or similar
                    handles = page.locator("#crop-range-slider .rc-slider-handle, #crop-range-slider [role='slider']")
                    track = page.locator("#crop-range-slider .rc-slider-track, #crop-range-slider .rc-slider-rail")
                    if handles.count() >= 2 and track.count() > 0:
                        track_box = track.first.bounding_box()
                        if track_box:
                            # Get min/max from slider (typically 1 to max_cols)
                            min_val = int(crop_slider.first.get_attribute("aria-valuemin") or "1")
                            max_val = int(crop_slider.first.get_attribute("aria-valuemax") or "30")
                            width = track_box["width"]
                            # Position as fraction: 3 -> 3/max, 10 -> 10/max
                            x_start = width * (3 - min_val) / (max_val - min_val) if max_val > min_val else width * 0.1
                            x_end = width * (10 - min_val) / (max_val - min_val) if max_val > min_val else width * 0.33
                            # Drag left handle to x_start
                            left_handle = handles.first
                            left_handle.hover()
                            page.mouse.down()
                            page.mouse.move(track_box["x"] + x_start, track_box["y"] + track_box["height"] / 2)
                            page.mouse.up()
                            page.wait_for_timeout(500)
                            # Drag right handle to x_end
                            right_handle = handles.nth(1)
                            right_handle.hover()
                            page.mouse.down()
                            page.mouse.move(track_box["x"] + x_end, track_box["y"] + track_box["height"] / 2)
                            page.mouse.up()
                            page.wait_for_timeout(1500)
                            report["crop_applied"] = True
                    else:
                        # Fallback: try clicking on track at approximate positions
                        track_box = page.locator("#crop-range-slider").first.bounding_box()
                        if track_box:
                            w = track_box["width"]
                            page.mouse.click(track_box["x"] + w * 0.1, track_box["y"] + track_box["height"] / 2)
                            page.wait_for_timeout(300)
                            page.mouse.click(track_box["x"] + w * 0.33, track_box["y"] + track_box["height"] / 2)
                            page.wait_for_timeout(1500)
                            report["crop_applied"] = True
                except Exception as e:
                    report["errors"].append(f"Crop drag failed: {e}")
                    report["crop_applied"] = False
            else:
                print("Crop slider not visible (schematic may have only 1 column). Skipping drag.")
                report["crop_applied"] = False

            # 5. After crop: check UNCOMMITTED badge, Commit/Reset buttons
            page.wait_for_timeout(1000)
            uncommitted = page.locator("#preview-badge:has-text('UNCOMMITTED')")
            report["uncommitted_badge_visible"] = uncommitted.count() > 0
            try:
                badge_style = page.locator("#preview-badge").evaluate(
                    "el => el ? window.getComputedStyle(el).display : 'none'"
                )
                report["uncommitted_badge_visible"] = badge_style != "none" and uncommitted.count() > 0
            except Exception:
                pass

            commit_visible = commit_btn.count() > 0
            reset_visible = reset_btn.count() > 0
            try:
                if commit_btn.count() > 0:
                    commit_visible = commit_btn.evaluate("el => window.getComputedStyle(el).display") != "none"
                if reset_btn.count() > 0:
                    reset_visible = reset_btn.evaluate("el => window.getComputedStyle(el).display") != "none"
            except Exception:
                pass
            report["commit_reset_buttons_visible"] = commit_visible and reset_visible

            # Screenshot 2: cropped state (or same if crop wasn't applied)
            print("Screenshot 2: Shelf Inspector (after crop attempt)...")
            page.screenshot(path=SCREENSHOTS_DIR / "shelf_inspector_after_crop.png", full_page=True)
            report["screenshots"].append("shelf_inspector_after_crop.png")

        except Exception as e:
            report["errors"].append(str(e))
            import traceback
            traceback.print_exc()
            try:
                page.screenshot(path=SCREENSHOTS_DIR / "99_error.png")
                report["screenshots"].append("99_error.png")
            except Exception:
                pass
        finally:
            browser.close()

    return report


def print_report(report: dict) -> None:
    print("\n" + "=" * 70)
    print("PLANOBRICKS SHELF INSPECTOR — CROP & PREVIEW COMPLIANCE VERIFICATION")
    print("=" * 70)
    print(f"URL: {report['url']}")
    print(f"Page load: {'OK' if report['page_load_ok'] else 'FAILED'}")
    if report.get("login_redirected"):
        print("LOGIN: Redirected to auth")
    if report["errors"]:
        print("\nErrors:")
        for e in report["errors"]:
            print(f"  - {e}")

    print("\n--- FINDINGS ---")
    print(f"  Shelf Inspector loaded:     {report['shelf_inspector_loaded']}")
    print(f"  Crop slider visible:        {report['crop_slider_visible']}")
    print(f"  Preview Compliance card:   {report['preview_compliance_visible']}")
    print(f"  Crop applied [3,10]:       {report['crop_applied']}")
    print(f"  UNCOMMITTED badge visible: {report['uncommitted_badge_visible']}")
    print(f"  Commit/Reset buttons:      {report['commit_reset_buttons_visible']}")

    print(f"\nScreenshots: {report['screenshots']}")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    args = parser.parse_args()
    report = run_verification(headless=args.headless)
    print_report(report)
    sys.exit(0 if report["page_load_ok"] and not report["errors"] else 1)
