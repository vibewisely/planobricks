"""Needleman-Wunsch sequence alignment for planogram compliance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ComplianceStatus(str, Enum):
    CORRECT = "Correct"
    INCORRECT_POSITION = "Incorrect Position"
    WRONG_SHELF = "Wrong Shelf"
    OUT_OF_STOCK = "Out-of-Stock"
    EXTRA_PRODUCT = "Extra Product"
    UNKNOWN = "Unknown"


@dataclass
class ProductResult:
    position: int
    expected_sku: str | None
    detected_sku: str | None
    status: ComplianceStatus
    confidence: float


@dataclass
class ShelfResult:
    shelf_row: int
    score: float
    products: list[ProductResult]


@dataclass
class ComplianceReport:
    overall_score: float
    shelves: list[ShelfResult]
    correct_count: int
    incorrect_position_count: int
    out_of_stock_count: int
    extra_product_count: int
    unknown_count: int


MATCH_SCORE = 2
POSITION_MISMATCH = 1
MISMATCH_PENALTY = -1
GAP_DETECTED = -2  # out-of-stock
GAP_EXPECTED = -1   # extra product


def align_shelf(
    expected: list[str],
    detected: list[str],
    all_expected_skus: set[str] | None = None,
) -> list[ProductResult]:
    """Align detected SKU sequence against expected using Needleman-Wunsch."""
    m, n = len(expected), len(detected)

    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + GAP_DETECTED
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + GAP_EXPECTED

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if expected[i - 1] == detected[j - 1]:
                match = dp[i - 1][j - 1] + MATCH_SCORE
            else:
                match = dp[i - 1][j - 1] + MISMATCH_PENALTY
            delete = dp[i - 1][j] + GAP_DETECTED
            insert = dp[i][j - 1] + GAP_EXPECTED
            dp[i][j] = max(match, delete, insert)

    results: list[ProductResult] = []
    i, j = m, n
    pos = max(m, n)

    while i > 0 or j > 0:
        if i > 0 and j > 0:
            if expected[i - 1] == detected[j - 1]:
                score_here = dp[i - 1][j - 1] + MATCH_SCORE
            else:
                score_here = dp[i - 1][j - 1] + MISMATCH_PENALTY

            if dp[i][j] == score_here:
                exp_sku = expected[i - 1]
                det_sku = detected[j - 1]
                if exp_sku == det_sku:
                    status = ComplianceStatus.CORRECT
                    conf = 0.98
                elif all_expected_skus and det_sku in all_expected_skus:
                    status = ComplianceStatus.INCORRECT_POSITION
                    conf = 0.85
                else:
                    status = ComplianceStatus.EXTRA_PRODUCT
                    conf = 0.70
                results.append(ProductResult(pos, exp_sku, det_sku, status, conf))
                i -= 1
                j -= 1
                pos -= 1
                continue

        if i > 0 and dp[i][j] == dp[i - 1][j] + GAP_DETECTED:
            results.append(
                ProductResult(pos, expected[i - 1], None, ComplianceStatus.OUT_OF_STOCK, 0.0)
            )
            i -= 1
        elif j > 0:
            results.append(
                ProductResult(pos, None, detected[j - 1], ComplianceStatus.EXTRA_PRODUCT, 0.75)
            )
            j -= 1
        pos -= 1

    results.reverse()
    for idx, r in enumerate(results):
        r.position = idx + 1
    return results


def compute_compliance(
    expected_shelves: dict[int, list[str]],
    detected_shelves: dict[int, list[str]],
) -> ComplianceReport:
    """Compute full compliance report across all shelves."""
    all_expected = {sku for skus in expected_shelves.values() for sku in skus}
    shelf_results: list[ShelfResult] = []
    total_correct = 0
    total_incorrect_pos = 0
    total_oos = 0
    total_extra = 0
    total_unknown = 0
    total_expected = sum(len(v) for v in expected_shelves.values())

    all_rows = sorted(set(expected_shelves.keys()) | set(detected_shelves.keys()))

    for row in all_rows:
        exp = expected_shelves.get(row, [])
        det = detected_shelves.get(row, [])
        products = align_shelf(exp, det, all_expected)

        row_correct = sum(1 for p in products if p.status == ComplianceStatus.CORRECT)
        row_incorrect = sum(1 for p in products if p.status == ComplianceStatus.INCORRECT_POSITION)
        row_oos = sum(1 for p in products if p.status == ComplianceStatus.OUT_OF_STOCK)
        row_extra = sum(1 for p in products if p.status == ComplianceStatus.EXTRA_PRODUCT)
        row_unknown = sum(1 for p in products if p.status == ComplianceStatus.UNKNOWN)

        row_expected = len(exp) if exp else 1
        row_score = row_correct / row_expected if row_expected > 0 else 0.0

        shelf_results.append(ShelfResult(row, round(row_score, 3), products))
        total_correct += row_correct
        total_incorrect_pos += row_incorrect
        total_oos += row_oos
        total_extra += row_extra
        total_unknown += row_unknown

    overall = total_correct / total_expected if total_expected > 0 else 0.0

    return ComplianceReport(
        overall_score=round(overall, 3),
        shelves=shelf_results,
        correct_count=total_correct,
        incorrect_position_count=total_incorrect_pos,
        out_of_stock_count=total_oos,
        extra_product_count=total_extra,
        unknown_count=total_unknown,
    )
