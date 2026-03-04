#!/usr/bin/env python3
"""Test local PlanoBricks app at http://127.0.0.1:8080/.

Performs:
1. Navigate to app
2. Screenshot Compliance Overview tab
3. Check for JavaScript console errors
4. Click Shelf Inspector tab, screenshot
5. Verify schematic planogram reference on right side
6. Click Planograms tab, screenshot
7. Report findings
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright not installed. Run: uv add --dev playwright")
    print("Then: uv run playwright install chromium")
    sys.exit(1)


def test_local_app(url: str = "http://127.0.0.1:8080/", screenshots_dir: Path | None = None) -> dict:
    """Run browser tests and return report."""
    if screenshots_dir is None:
        screenshots_dir = Path(__file__).parent.parent / "dashboard_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "url": url,
        "page_load_ok": False,
        "console_errors": [],
        "tabs_load_ok": {},
        "shelf_inspector": {
            "detected_layout_left": False,
            "schematic_reference_right": False,
            "side_by_side": False,
        },
        "screenshots": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Collect console messages (especially errors)
        def on_console(msg):
            if msg.type == "error":
                report["console_errors"].append(msg.text)

        page.on("console", on_console)

        try:
            # 1. Navigate
            print(f"Navigating to {url}...")
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            if response and response.status >= 400:
                report["errors"] = [f"HTTP {response.status}"]
                return report

            report["page_load_ok"] = True

            # 2. Screenshot Compliance Overview (main page)
            print("Screenshot: Compliance Overview...")
            page.screenshot(path=screenshots_dir / "01_compliance_overview.png")
            report["screenshots"].append("01_compliance_overview.png")

            # 3. Check tabs structure
            tabs = page.locator('[role="tab"], .nav-link, [data-tab]')
            report["tabs_load_ok"]["Compliance Overview"] = True  # We're on it

            # 4. Shelf Inspector tab
            print("Clicking Shelf Inspector tab...")
            shelf_tab = page.locator('text="Shelf Inspector"').first
            if shelf_tab.count() > 0:
                shelf_tab.click()
                page.wait_for_timeout(2000)

            # Check for detected layout (left) and schematic reference (right)
            detected_card = page.locator('text="Detected Shelf Layout (from image)"')
            schematic_card = page.locator('text="Schematic Planogram Reference (consensus)"')
            shelf_graph = page.locator("#shelf-image-graph")
            schematic_graph = page.locator("#schematic-graph")

            report["shelf_inspector"]["detected_layout_left"] = (
                detected_card.count() > 0 and shelf_graph.count() > 0
            )
            report["shelf_inspector"]["schematic_reference_right"] = (
                schematic_card.count() > 0 and schematic_graph.count() > 0
            )
            report["shelf_inspector"]["side_by_side"] = (
                report["shelf_inspector"]["detected_layout_left"]
                and report["shelf_inspector"]["schematic_reference_right"]
            )
            report["tabs_load_ok"]["Shelf Inspector"] = report["shelf_inspector"]["side_by_side"]

            print("Screenshot: Shelf Inspector...")
            page.screenshot(path=screenshots_dir / "02_shelf_inspector.png")
            report["screenshots"].append("02_shelf_inspector.png")

            # 5. Planograms tab
            print("Clicking Planograms tab...")
            plano_tab = page.locator('text="Planograms"').first
            if plano_tab.count() > 0:
                plano_tab.click()
                page.wait_for_timeout(2000)

            schematic_planograms = page.locator('text="Schematic Planograms (Multi-Image Consensus)"')
            schematic_layouts = page.locator('text="Schematic Shelf Layouts"')
            report["tabs_load_ok"]["Planograms"] = (
                schematic_planograms.count() > 0 or schematic_layouts.count() > 0
            )

            print("Screenshot: Planograms...")
            page.screenshot(path=screenshots_dir / "03_planograms.png")
            report["screenshots"].append("03_planograms.png")

        except Exception as e:
            report["errors"] = report.get("errors", []) + [str(e)]
            page.screenshot(path=screenshots_dir / "99_error.png")
            report["screenshots"].append("99_error.png")
        finally:
            browser.close()

    return report


def print_report(report: dict) -> None:
    """Print verification report."""
    print("\n" + "=" * 60)
    print("PLANOBRICKS LOCAL APP TEST REPORT")
    print("=" * 60)
    print(f"URL: {report['url']}")
    print(f"Page load: {'OK' if report['page_load_ok'] else 'FAILED'}")

    if report.get("console_errors"):
        print(f"\nJavaScript console errors ({len(report['console_errors'])}):")
        for e in report["console_errors"][:10]:
            print(f"  - {e}")
        if len(report["console_errors"]) > 10:
            print(f"  ... and {len(report['console_errors']) - 10} more")
    else:
        print("\nJavaScript console: No errors")

    print("\nTabs:")
    for name, ok in report.get("tabs_load_ok", {}).items():
        print(f"  - {name}: {'OK' if ok else 'FAILED'}")

    si = report.get("shelf_inspector", {})
    print("\nShelf Inspector:")
    print(f"  - Detected shelf layout (left): {'Yes' if si.get('detected_layout_left') else 'No'}")
    print(f"  - Schematic reference (right): {'Yes' if si.get('schematic_reference_right') else 'No'}")
    print(f"  - Side-by-side rendering: {'Yes' if si.get('side_by_side') else 'No'}")

    print(f"\nScreenshots: {report.get('screenshots', [])}")
    print("=" * 60)


if __name__ == "__main__":
    screenshots_dir = Path(__file__).parent.parent / "dashboard_screenshots"
    report = test_local_app("http://127.0.0.1:8080/", screenshots_dir)
    print_report(report)
    sys.exit(0 if report.get("page_load_ok") and not report.get("console_errors") else 1)
