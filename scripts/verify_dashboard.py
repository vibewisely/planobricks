#!/usr/bin/env python3
"""Verify PlanoBricks Planogram Compliance Dashboard.

Runs Playwright to navigate the deployed app, check each tab, and capture screenshots.
Requires: uv add --dev playwright && uv run playwright install chromium

Usage:
    uv run python scripts/verify_dashboard.py [--url URL] [--screenshots-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright not installed. Run: uv add --dev playwright")
    print("Then: uv run playwright install chromium")
    sys.exit(1)


DEFAULT_URL = "https://planobricks-dev-7474651516019640.aws.databricksapps.com"
DEFAULT_SCREENSHOTS_DIR = Path(__file__).parent.parent / "dashboard_screenshots"


def verify_dashboard(url: str, screenshots_dir: Path, headless: bool = False) -> dict:
    """Verify dashboard and return report."""
    report = {
        "url": url,
        "page_load_ok": False,
        "errors": [],
        "tabs": {},
        "screenshots": [],
    }
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        try:
            # 1. Navigate and check initial load
            print(f"Navigating to {url}...")
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass  # Continue even if networkidle times out
            if response and response.status >= 400:
                report["errors"].append(f"HTTP {response.status}")
                return report

            # Check for login redirect (Databricks Apps often require auth)
            if "login" in page.url.lower() or "accounts.databricks" in page.url:
                report["errors"].append(
                    "Redirected to login - you may need to authenticate first. "
                    "Run with headless=False to log in interactively."
                )
                page.screenshot(path=screenshots_dir / "00_login_redirect.png")
                report["screenshots"].append("00_login_redirect.png")
                browser.close()
                return report

            report["page_load_ok"] = True
            page.screenshot(path=screenshots_dir / "00_initial_load.png")
            report["screenshots"].append("00_initial_load.png")

            # 2. Compliance Overview tab (default)
            print("Checking Compliance Overview tab...")
            tab_overview = {}
            try:
                # KPI cards
                kpis = page.locator(".card-body .h3, .card-body h3")
                tab_overview["kpi_cards"] = kpis.count() >= 4
                # Charts
                charts = page.locator(".js-plotly-plot, [class*='plotly']")
                tab_overview["charts_visible"] = charts.count() >= 3
                # Data table
                table = page.locator("#compliance-table, table, [role='grid']")
                tab_overview["data_table"] = table.count() > 0
                tab_overview["ok"] = all(tab_overview.values())
            except Exception as e:
                tab_overview["ok"] = False
                tab_overview["error"] = str(e)
            report["tabs"]["Compliance Overview"] = tab_overview
            page.screenshot(path=screenshots_dir / "01_compliance_overview.png")
            report["screenshots"].append("01_compliance_overview.png")

            # 3. Shelf Inspector tab
            print("Checking Shelf Inspector tab...")
            shelf_tab = page.locator('text="Shelf Inspector"').first
            if shelf_tab.count() > 0:
                shelf_tab.click()
                page.wait_for_timeout(1500)
            tab_inspector = {}
            try:
                dropdown = page.locator("#shelf-selector, [role='combobox'], select")
                tab_inspector["dropdown"] = dropdown.count() > 0
                # Bounding boxes / graph
                graph = page.locator("#shelf-image-graph, .js-plotly-plot")
                tab_inspector["bounding_boxes"] = graph.count() > 0
                tab_inspector["ok"] = tab_inspector["dropdown"] and tab_inspector["bounding_boxes"]
            except Exception as e:
                tab_inspector["ok"] = False
                tab_inspector["error"] = str(e)
            report["tabs"]["Shelf Inspector"] = tab_inspector
            page.screenshot(path=screenshots_dir / "02_shelf_inspector.png")
            report["screenshots"].append("02_shelf_inspector.png")

            # 4. Planograms tab
            print("Checking Planograms tab...")
            plano_tab = page.locator('text="Planograms"').first
            if plano_tab.count() > 0:
                plano_tab.click()
                page.wait_for_timeout(1500)
            tab_planograms = {}
            try:
                ref_summary = page.locator('text="Planogram Reference Summary"')
                tab_planograms["summary_section"] = ref_summary.count() > 0
                sequences = page.locator('text="Reference Planogram Brand Sequences"')
                tab_planograms["sequences_section"] = sequences.count() > 0
                tab_planograms["ok"] = tab_planograms["summary_section"]
            except Exception as e:
                tab_planograms["ok"] = False
                tab_planograms["error"] = str(e)
            report["tabs"]["Planograms"] = tab_planograms
            page.screenshot(path=screenshots_dir / "03_planograms.png")
            report["screenshots"].append("03_planograms.png")

            # 5. Dataset tab
            print("Checking Dataset tab...")
            dataset_tab = page.locator('text="Dataset"').first
            if dataset_tab.count() > 0:
                dataset_tab.click()
                page.wait_for_timeout(1500)
            tab_dataset = {}
            try:
                about = page.locator('text="About the Dataset"')
                tab_dataset["about_section"] = about.count() > 0
                grocery = page.locator('text="Grocery Dataset"')
                tab_dataset["dataset_info"] = grocery.count() > 0
                tab_dataset["ok"] = tab_dataset["about_section"]
            except Exception as e:
                tab_dataset["ok"] = False
                tab_dataset["error"] = str(e)
            report["tabs"]["Dataset"] = tab_dataset
            page.screenshot(path=screenshots_dir / "04_dataset.png")
            report["screenshots"].append("04_dataset.png")

        except Exception as e:
            report["errors"].append(str(e))
            page.screenshot(path=screenshots_dir / "99_error.png")
            report["screenshots"].append("99_error.png")
        finally:
            browser.close()

    return report


def print_report(report: dict) -> None:
    """Print verification report."""
    print("\n" + "=" * 60)
    print("PLANOBRICKS DASHBOARD VERIFICATION REPORT")
    print("=" * 60)
    print(f"URL: {report['url']}")
    print(f"Page load: {'OK' if report['page_load_ok'] else 'FAILED'}")
    if report["errors"]:
        print("\nErrors:")
        for e in report["errors"]:
            print(f"  - {e}")
    print("\nTabs:")
    for name, details in report["tabs"].items():
        ok = details.get("ok", False)
        status = "OK" if ok else "FAILED"
        print(f"  - {name}: {status}")
        for k, v in details.items():
            if k not in ("ok", "error") and isinstance(v, bool):
                print(f"      {k}: {v}")
        if "error" in details:
            print(f"      error: {details['error']}")
    print(f"\nScreenshots saved: {len(report['screenshots'])}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PlanoBricks dashboard")
    parser.add_argument("--url", default=DEFAULT_URL, help="Dashboard URL")
    parser.add_argument("--screenshots-dir", type=Path, default=DEFAULT_SCREENSHOTS_DIR)
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    args = parser.parse_args()

    report = verify_dashboard(args.url, args.screenshots_dir, headless=args.headless)
    print_report(report)

    all_ok = report["page_load_ok"] and all(
        t.get("ok", False) for t in report["tabs"].values()
    ) and not report["errors"]
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
