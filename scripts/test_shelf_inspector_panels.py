#!/usr/bin/env python3
"""Test Shelf Inspector tab on deployed PlanoBricks app.

Verifies:
1. Three panels side by side: Actual Shelf Photo | Detected Layout | Schematic Reference
2. Whether photo panel shows placeholder vs actual image
3. Dropdown selection and re-render with S5 image
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

URL = "https://planobricks-dev-7474651516019640.aws.databricksapps.com/"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "dashboard_screenshots"


def test_shelf_inspector(headless: bool = True) -> dict:
    """Run Shelf Inspector panel tests and return report."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "url": URL,
        "page_load_ok": False,
        "login_redirected": False,
        "panels": {
            "left_actual_photo": {"visible": False, "has_real_image": None, "placeholder_text": None},
            "middle_detected_layout": {"visible": False, "has_bounding_boxes": False},
            "right_schematic_reference": {"visible": False, "has_grid_blocks": False},
        },
        "dropdown_options": [],
        "s5_selection": {"selected": None, "success": False},
        "screenshots": [],
        "errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
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

            # Check for login redirect
            if "login" in page.url.lower() or "accounts.databricks" in page.url:
                report["login_redirected"] = True
                if not headless:
                    print("Login detected. Please log in in the browser window. Waiting up to 90s...")
                    try:
                        page.wait_for_url(
                            re.compile(r"databricksapps\.com"),
                            timeout=90000,
                        )
                        report["login_redirected"] = False
                        report["page_load_ok"] = True
                        # Wait for app to render (Dash/React)
                        page.wait_for_timeout(5000)
                        # Wait for main content
                        page.wait_for_selector(".navbar, #main-tabs, [role='tab']", timeout=15000)
                    except Exception:
                        report["errors"].append("Timed out waiting for login")
                        page.screenshot(path=SCREENSHOTS_DIR / "00_login_redirect.png")
                        report["screenshots"].append("00_login_redirect.png")
                        browser.close()
                        return report
                else:
                    report["errors"].append("Redirected to login - run with --no-headless to log in")
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
                # Try alternate selectors (Dash Bootstrap tabs)
                shelf_tab = page.locator('[role="tab"]:has-text("Shelf Inspector")').first
            if shelf_tab.count() == 0:
                shelf_tab = page.locator('.nav-link:has-text("Shelf Inspector")').first
            if shelf_tab.count() == 0:
                report["errors"].append("Shelf Inspector tab not found")
                page.screenshot(path=SCREENSHOTS_DIR / "99_error.png")
                report["screenshots"].append("99_error.png")
                # Debug: save page content
                try:
                    with open(SCREENSHOTS_DIR / "page_content.html", "w") as f:
                        f.write(page.content())
                except Exception:
                    pass
                browser.close()
                return report

            shelf_tab.click()
            page.wait_for_timeout(3000)

            # 3. Verify three panels
            left_header = page.locator('text="Actual Shelf Photo"')
            middle_header = page.locator('text="Detected Layout (bounding boxes)"')
            right_header = page.locator('text="Schematic Reference (consensus)"')

            report["panels"]["left_actual_photo"]["visible"] = left_header.count() > 0
            report["panels"]["middle_detected_layout"]["visible"] = middle_header.count() > 0
            report["panels"]["right_schematic_reference"]["visible"] = right_header.count() > 0

            # Check photo panel: real image vs placeholder
            photo_container = page.locator("#shelf-photo-container")
            img = photo_container.locator("img")
            placeholder = page.locator('text="Photo available when running on Databricks Apps"')

            if img.count() > 0:
                report["panels"]["left_actual_photo"]["has_real_image"] = True
                report["panels"]["left_actual_photo"]["placeholder_text"] = None
            elif placeholder.count() > 0:
                report["panels"]["left_actual_photo"]["has_real_image"] = False
                report["panels"]["left_actual_photo"]["placeholder_text"] = (
                    "Photo available when running on Databricks Apps (reads from UC Volume)"
                )
            else:
                report["panels"]["left_actual_photo"]["has_real_image"] = False
                report["panels"]["left_actual_photo"]["placeholder_text"] = "Unknown (no img, no placeholder)"

            # Check middle: bounding boxes (Plotly graph)
            shelf_graph = page.locator("#shelf-image-graph")
            report["panels"]["middle_detected_layout"]["has_bounding_boxes"] = shelf_graph.count() > 0

            # Check right: schematic (Plotly graph)
            schematic_graph = page.locator("#schematic-graph")
            report["panels"]["right_schematic_reference"]["has_grid_blocks"] = schematic_graph.count() > 0

            # Screenshot 1: initial Shelf Inspector view
            print("Screenshot: Shelf Inspector (initial)...")
            page.screenshot(path=SCREENSHOTS_DIR / "shelf_inspector_initial.png")
            report["screenshots"].append("shelf_inspector_initial.png")

            # 4. Get dropdown options and select one with S5
            dropdown = page.locator("#shelf-selector").locator("..").locator("input, .Select-control, [role='combobox']").first
            if dropdown.count() == 0:
                dropdown = page.locator("#shelf-selector")
            if dropdown.count() > 0:
                dropdown.click()
                page.wait_for_timeout(800)
                # Dash dcc.Dropdown uses react-select; options appear in menu
                s5_option = page.locator('text=/S5/').first
                if s5_option.count() > 0:
                    s5_option.click()
                    page.wait_for_timeout(2500)
                    report["s5_selection"]["selected"] = "S5 image"
                    report["s5_selection"]["success"] = True
                else:
                    # Fallback: click any option that's not the first
                    opts = page.locator(".Select-option, [role='option']")
                    if opts.count() > 1:
                        opts.nth(1).click()
                        page.wait_for_timeout(2500)
                        report["s5_selection"]["selected"] = "second option"
                        report["s5_selection"]["success"] = True

            # Re-check panels after selection (in case we changed image)
            if report["s5_selection"]["success"]:
                img2 = page.locator("#shelf-photo-container img")
                placeholder2 = page.locator('text="Photo available when running on Databricks Apps"')
                report["panels"]["left_actual_photo"]["has_real_image_after_s5"] = img2.count() > 0
                report["panels"]["left_actual_photo"]["placeholder_after_s5"] = placeholder2.count() > 0

            # Screenshot 2: after S5 selection
            print("Screenshot: Shelf Inspector (after S5 selection)...")
            page.screenshot(path=SCREENSHOTS_DIR / "shelf_inspector_after_s5.png")
            report["screenshots"].append("shelf_inspector_after_s5.png")

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
    """Print detailed report."""
    print("\n" + "=" * 70)
    print("PLANOBRICKS SHELF INSPECTOR PANEL TEST REPORT")
    print("=" * 70)
    print(f"URL: {report['url']}")
    print(f"Page load: {'OK' if report['page_load_ok'] else 'FAILED'}")
    if report.get("login_redirected"):
        print("LOGIN: Redirected to auth - run with headless=False to authenticate")
    if report["errors"]:
        print("\nErrors:")
        for e in report["errors"]:
            print(f"  - {e}")

    print("\n--- THREE PANELS (side by side) ---")
    p = report["panels"]
    print(f"  Left  - Actual Shelf Photo:        visible={p['left_actual_photo']['visible']}")
    print(f"          Has real JPG image:        {p['left_actual_photo']['has_real_image']}")
    print(f"          Placeholder text shown:    {p['left_actual_photo'].get('placeholder_text', 'N/A')}")
    print(f"  Middle - Detected Layout (boxes):  visible={p['middle_detected_layout']['visible']}, has_boxes={p['middle_detected_layout']['has_bounding_boxes']}")
    print(f"  Right  - Schematic Reference:      visible={p['right_schematic_reference']['visible']}, has_grid={p['right_schematic_reference']['has_grid_blocks']}")

    if report["panels"]["left_actual_photo"].get("placeholder_text"):
        print("\n  *** PHOTO PANEL: Shows 'Photo available when running on Databricks Apps' instead of actual image ***")

    print("\n--- DROPDOWN / S5 SELECTION ---")
    print(f"  Selected: {report['s5_selection'].get('selected', 'N/A')}")
    print(f"  Success:  {report['s5_selection']['success']}")

    print(f"\nScreenshots: {report['screenshots']}")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-headless", action="store_true", help="Show browser for interactive login")
    args = parser.parse_args()
    report = test_shelf_inspector(headless=not args.no_headless)
    print_report(report)
    sys.exit(0 if report["page_load_ok"] and not report["errors"] else 1)
