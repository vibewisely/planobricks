"""Build schematic planograms from multi-image consensus and compute compliance
using Needleman-Wunsch sequence alignment.

Each physical planogram section is photographed multiple times from different
cameras and angles. We build a "schematic" reference by:
1. Clustering products into shelf rows using y-coordinate gaps
2. Within each row, ordering products left-to-right by x-coordinate
3. Across multiple images of the same view, building a consensus sequence
4. Filling Unknown/Other slots with the most common neighboring brand
5. Comparing any image against the schematic using NW alignment
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter

from grocery_data import Product, ShelfImage, BRAND_COLORS


# ─── Shelf Row Clustering ─────────────────────────────────────────

def cluster_into_rows(products: list[Product], gap_threshold: int = 80) -> list[list[Product]]:
    """Split products into shelf rows based on y-coordinate gaps."""
    if not products:
        return []
    sorted_by_y = sorted(products, key=lambda p: p.y)
    rows: list[list[Product]] = [[sorted_by_y[0]]]
    for p in sorted_by_y[1:]:
        if p.y - rows[-1][-1].y > gap_threshold:
            rows.append([])
        rows[-1].append(p)
    for row in rows:
        row.sort(key=lambda p: p.x)
    return rows


def row_brand_sequence(row: list[Product]) -> list[str]:
    return [p.brand for p in row]


# ─── Needleman-Wunsch Alignment ──────────────────────────────────

MATCH_SCORE = 2
MISMATCH_PENALTY = -1
GAP_PENALTY = -2


@dataclass
class AlignedPair:
    position: int
    expected: str | None
    detected: str | None
    status: str

    @property
    def expected_display(self) -> str:
        return self.expected or "—"

    @property
    def detected_display(self) -> str:
        return self.detected or "—"


def needleman_wunsch(ref: list[str], det: list[str]) -> list[AlignedPair]:
    """Align two brand sequences using Needleman-Wunsch global alignment."""
    n, m = len(ref), len(det)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP_PENALTY
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP_PENALTY

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = dp[i - 1][j - 1] + (MATCH_SCORE if ref[i - 1] == det[j - 1] else MISMATCH_PENALTY)
            delete = dp[i - 1][j] + GAP_PENALTY
            insert = dp[i][j - 1] + GAP_PENALTY
            dp[i][j] = max(match, delete, insert)

    aligned: list[AlignedPair] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            score = MATCH_SCORE if ref[i - 1] == det[j - 1] else MISMATCH_PENALTY
            if dp[i][j] == dp[i - 1][j - 1] + score:
                if ref[i - 1] == det[j - 1]:
                    status = "Correct"
                elif det[j - 1] in ref:
                    status = "Wrong Position"
                else:
                    status = "Substitution"
                aligned.append(AlignedPair(0, ref[i - 1], det[j - 1], status))
                i -= 1
                j -= 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + GAP_PENALTY:
            aligned.append(AlignedPair(0, ref[i - 1], None, "Out-of-Stock"))
            i -= 1
        else:
            aligned.append(AlignedPair(0, None, det[j - 1], "Extra"))
            j -= 1

    aligned.reverse()
    for idx, a in enumerate(aligned):
        a.position = idx + 1
    return aligned


def alignment_score(aligned: list[AlignedPair]) -> float:
    """Compliance score: correct / total expected positions."""
    correct = sum(1 for a in aligned if a.status == "Correct")
    expected = sum(1 for a in aligned if a.expected is not None)
    return correct / expected if expected else 0.0


# ─── Schematic Planogram Builder ──────────────────────────────────

@dataclass
class SchematicRow:
    row_index: int
    brands: list[str]
    avg_y: float = 0.0

    @property
    def display(self) -> str:
        return " | ".join(self.brands)


SchematicKey = tuple[str, str, str]  # (planogram_id, num_shelves, shelf_rank)


@dataclass
class SchematicPlanogram:
    planogram_id: str
    num_shelves: str
    shelf_rank: str
    rows: list[SchematicRow] = field(default_factory=list)
    source_images: list[str] = field(default_factory=list)

    @property
    def total_products(self) -> int:
        return sum(len(r.brands) for r in self.rows)

    @property
    def label(self) -> str:
        return f"P{self.planogram_id}/{self.num_shelves}s/R{self.shelf_rank}"


def _fill_unknowns(brands: list[str]) -> list[str]:
    """Replace Unknown/Other with the nearest identified neighbor brand."""
    result = list(brands)
    identified = [(i, b) for i, b in enumerate(result) if b not in ("Unknown", "Other")]

    for i, b in enumerate(result):
        if b in ("Unknown", "Other"):
            best = None
            best_dist = float("inf")
            for idx, ib in identified:
                dist = abs(idx - i)
                if dist < best_dist:
                    best_dist = dist
                    best = ib
            if best:
                result[i] = best
    return result


def _build_consensus_row(all_row_brands: list[list[str]]) -> list[str]:
    """Build a consensus brand sequence from multiple images of the same shelf row.

    Uses the longest sequence as the template, then for each position takes the
    most common non-Unknown brand across all images (via majority vote).
    """
    if not all_row_brands:
        return []
    non_empty = [r for r in all_row_brands if r]
    if not non_empty:
        return []
    max_len = max(len(r) for r in non_empty)
    consensus: list[str] = []

    for pos in range(max_len):
        votes: list[str] = []
        for row in non_empty:
            if pos < len(row):
                votes.append(row[pos])
        real_votes = [v for v in votes if v not in ("Unknown", "Other")]
        if real_votes:
            consensus.append(Counter(real_votes).most_common(1)[0][0])
        elif votes:
            consensus.append(Counter(votes).most_common(1)[0][0])
        else:
            consensus.append("Unknown")
    return consensus


def build_schematics(shelves: list[ShelfImage]) -> dict[SchematicKey, SchematicPlanogram]:
    """Build schematic planograms grouped by (planogram_id, num_shelves, shelf_rank).

    Each group contains images of the exact same physical shelf section, so the
    consensus truly represents that section. We:
    1. Cluster each image's products into rows
    2. Align rows across images by row index (first row = top visible shelf)
    3. Build consensus per row via majority vote
    4. Fill remaining Unknown positions with nearest neighbor
    """
    groups: dict[SchematicKey, list[ShelfImage]] = {}
    for s in shelves:
        key = (s.planogram_id, s.num_shelves, s.shelf_rank)
        groups.setdefault(key, []).append(s)

    schematics: dict[SchematicKey, SchematicPlanogram] = {}

    for (pid, ns, sr), images in groups.items():
        num_shelves_int = int(ns) if ns.isdigit() else 2
        all_image_rows: list[list[list[str]]] = []

        for img in images:
            rows = cluster_into_rows(img.products)
            row_brands = [row_brand_sequence(r) for r in rows]
            if len(row_brands) < num_shelves_int:
                row_brands.extend([] for _ in range(num_shelves_int - len(row_brands)))
            elif len(row_brands) > num_shelves_int:
                row_brands = row_brands[:num_shelves_int]
            all_image_rows.append(row_brands)

        schematic_rows: list[SchematicRow] = []
        for row_idx in range(num_shelves_int):
            per_image = [img_rows[row_idx] for img_rows in all_image_rows if row_idx < len(img_rows)]
            consensus = _build_consensus_row(per_image)
            filled = _fill_unknowns(consensus)
            schematic_rows.append(SchematicRow(row_index=row_idx, brands=filled))

        sp = SchematicPlanogram(
            planogram_id=pid,
            num_shelves=ns,
            shelf_rank=sr,
            rows=schematic_rows,
            source_images=[img.filename for img in images],
        )
        schematics[(pid, ns, sr)] = sp

    return schematics


# ─── Compliance Computation ───────────────────────────────────────

@dataclass
class ShelfComplianceResult:
    filename: str
    planogram_id: str
    num_shelves: str
    score: float
    total_products: int
    correct: int
    wrong_position: int
    substitution: int
    out_of_stock: int
    extra: int
    row_results: list[RowComplianceResult] = field(default_factory=list)
    aligned_pairs: list[AlignedPair] = field(default_factory=list)


@dataclass
class RowComplianceResult:
    row_index: int
    reference_brands: list[str]
    detected_brands: list[str]
    aligned: list[AlignedPair]
    score: float


def compute_compliance(
    shelf: ShelfImage,
    schematics: dict[SchematicKey, SchematicPlanogram],
) -> ShelfComplianceResult:
    """Compare a shelf image against its schematic planogram using NW alignment."""
    key = (shelf.planogram_id, shelf.num_shelves, shelf.shelf_rank)
    schematic = schematics.get(key)

    if not schematic:
        return ShelfComplianceResult(
            filename=shelf.filename, planogram_id=shelf.planogram_id,
            num_shelves=shelf.num_shelves, score=0.0,
            total_products=shelf.num_products,
            correct=0, wrong_position=0, substitution=0, out_of_stock=0, extra=0,
        )

    detected_rows = cluster_into_rows(shelf.products)
    num_rows = len(schematic.rows)
    if len(detected_rows) < num_rows:
        detected_rows.extend([] for _ in range(num_rows - len(detected_rows)))

    all_aligned: list[AlignedPair] = []
    row_results: list[RowComplianceResult] = []

    for i in range(num_rows):
        ref_brands = schematic.rows[i].brands
        det_brands = row_brand_sequence(detected_rows[i]) if i < len(detected_rows) else []
        aligned = needleman_wunsch(ref_brands, det_brands)
        row_score = alignment_score(aligned)
        all_aligned.extend(aligned)
        row_results.append(RowComplianceResult(
            row_index=i,
            reference_brands=ref_brands,
            detected_brands=det_brands,
            aligned=aligned,
            score=round(row_score, 3),
        ))

    total_correct = sum(1 for a in all_aligned if a.status == "Correct")
    total_wp = sum(1 for a in all_aligned if a.status == "Wrong Position")
    total_sub = sum(1 for a in all_aligned if a.status == "Substitution")
    total_oos = sum(1 for a in all_aligned if a.status == "Out-of-Stock")
    total_extra = sum(1 for a in all_aligned if a.status == "Extra")
    total_expected = sum(1 for a in all_aligned if a.expected is not None)
    score = total_correct / total_expected if total_expected else 0.0

    return ShelfComplianceResult(
        filename=shelf.filename,
        planogram_id=shelf.planogram_id,
        num_shelves=shelf.num_shelves,
        score=round(score, 3),
        total_products=shelf.num_products,
        correct=total_correct,
        wrong_position=total_wp,
        substitution=total_sub,
        out_of_stock=total_oos,
        extra=total_extra,
        row_results=row_results,
        aligned_pairs=all_aligned,
    )
