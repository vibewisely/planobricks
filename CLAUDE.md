# PlanoBricks

Planogram compliance platform for Retail/CPG, built on Databricks. Uses computer vision to detect shelf products, classify SKUs, and verify compliance against reference planograms.

**Full product specification**: See `PRD.md` for the comprehensive Product Requirements Document.

## Product Domain

- **Planogram**: Expected shelf layout defining which SKUs go where
- **Realogram**: Actual shelf layout captured via photograph
- **Compliance score**: Ratio of correctly placed products to expected (0.0 - 1.0)
- **4-stage CV pipeline**: Shelf detection (YOLOv8) → Product detection (YOLOv8) → SKU classification (EfficientNet-B4) → Compliance alignment (Needleman-Wunsch)
- **Unity Catalog**: `serverless_stable_wunnava_catalog` catalog with planobricks_bronze/planobricks_silver/planobricks_gold/planobricks_reference/planobricks_ml schemas

## Project Structure

```
planobricks/
├── src/planobricks/          # Package source code
│   ├── backend/              # FastAPI app (APX)
│   │   ├── models.py         # Pydantic models (In/Out/ListOut)
│   │   ├── router.py         # API routes
│   │   ├── compliance_engine.py  # Needleman-Wunsch alignment
│   │   └── pipeline.py       # CV pipeline orchestration
│   ├── ui/                   # React frontend (APX)
│   ├── pipelines/            # Lakeflow SDP (bronze/silver/gold)
│   └── training/             # Model training scripts
├── tests/                    # Test suite
├── notebooks/                # Databricks notebooks
├── resources/                # DABs resource definitions
├── PRD.md                    # Product Requirements Document
├── pyproject.toml            # Project config & dependencies
├── CLAUDE.md                 # This file — project context
└── .mcp.json                 # Databricks MCP server config
```

## Development

- **Package manager**: `uv` — use `uv add <pkg>` to add dependencies, `uv run <cmd>` to run scripts
- **Python version**: 3.11+
- **App framework**: APX (FastAPI + React) — full-stack Databricks App
- **Run**: `uv run python main.py` or `uv run python -m planobricks`
- **Test**: `uv run pytest`
- **Lint**: `uv run ruff check .`
- **Format**: `uv run ruff format .`

## Conventions

- Use `src/` layout for package code
- Type hints on all function signatures
- Tests go in `tests/` mirroring the `src/` structure
- Follow APX 3-model pattern for API: `EntityIn`, `EntityOut`, `EntityListOut`
- Databricks config profile: `planobricks-mar2`

## Databricks

- MCP server configured in `.mcp.json` with profile `planobricks-mar2`
- Use `databricks-sdk` for API interactions
- Use Unity Catalog for data governance (`serverless_stable_wunnava_catalog` catalog)
- Model Serving endpoints: `planobricks-shelf-detector`, `planobricks-product-detector`, `planobricks-sku-classifier`
- Deployment via Databricks Asset Bundles (DABs)
