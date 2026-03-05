"""PlanoBricks — Planogram Compliance Dashboard.

Interactive dashboard built on the Grocery Dataset
(Varol & Kuzu, "Toward Retail Product Recognition on Grocery Shelves", ICIVC 2014).

All 13,184 products enriched with brand names identified by Databricks Foundation
Model API (ai_query + Claude Haiku 4.5 vision). See notebooks/01_brand_identification.py.

Compliance computed via Needleman-Wunsch sequence alignment against schematic
planograms built from multi-image consensus.
"""

from __future__ import annotations

import base64
import logging
import os

import dash
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, dash_table

import grocery_data as gd
import planogram_engine as pe
import store_manager as sm

log = logging.getLogger(__name__)

VOLUME_BASE = "/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images"
SHELF_IMAGES_DIR = f"{VOLUME_BASE}/ShelfImages"

_sdk_client = None


def _get_sdk_client():
    """Lazy-init Databricks SDK WorkspaceClient."""
    global _sdk_client
    if _sdk_client is None:
        try:
            from databricks.sdk import WorkspaceClient
            _sdk_client = WorkspaceClient()
            print(f"[PlanoBricks] SDK initialized, host={_sdk_client.config.host}", flush=True)
        except Exception as e:
            print(f"[PlanoBricks] SDK init failed: {e}", flush=True)
    return _sdk_client


_image_cache: dict[str, str] = {}


def _read_volume_image(filename: str) -> str | None:
    """Read a shelf image from UC Volume via SDK, return base64 string or None."""
    if filename in _image_cache:
        return _image_cache[filename]

    local_path = os.path.join(
        os.environ.get("SHELF_IMAGES_PATH", SHELF_IMAGES_DIR), filename
    )
    if os.path.isfile(local_path):
        print(f"[PlanoBricks] Loading image from local: {local_path}", flush=True)
        with open(local_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        _image_cache[filename] = b64
        return b64

    w = _get_sdk_client()
    if w is None:
        print(f"[PlanoBricks] No SDK client — cannot load {filename}", flush=True)
        return None

    try:
        volume_path = f"{SHELF_IMAGES_DIR}/{filename}"
        print(f"[PlanoBricks] Downloading from volume: {volume_path}", flush=True)
        resp = w.files.download(volume_path)
        raw = resp.contents.read()
        b64 = base64.b64encode(raw).decode()
        _image_cache[filename] = b64
        print(f"[PlanoBricks] Loaded {filename} ({len(raw)} bytes)", flush=True)
        return b64
    except Exception as e:
        print(f"[PlanoBricks] Failed to read {filename}: {type(e).__name__}: {e}", flush=True)
        return None


app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
    title="PlanoBricks — Planogram Compliance",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

STATUS_BADGE = {
    "Correct": "success",
    "Wrong Position": "warning",
    "Mismatch": "info",
    "Out-of-Stock": "danger",
    "Extra": "primary",
    "Unknown": "secondary",
}


def kpi_card(title: str, value: str, icon: str, color: str = "primary") -> dbc.Col:
    return dbc.Col(dbc.Card(dbc.CardBody(html.Div([
        html.I(className=f"fas fa-{icon} fa-2x text-{color} me-3"),
        html.Div([
            html.P(title, className="text-muted mb-0", style={"fontSize": "0.8rem"}),
            html.H3(value, className=f"mb-0 fw-bold text-{color}"),
        ]),
    ], className="d-flex align-items-center")), className="shadow-sm border-0 h-100"),
        xs=6, lg=3, className="mb-3")


# ═══════════════════════════════════════════════════════════════════
# TAB 1 — COMPLIANCE OVERVIEW
# ═══════════════════════════════════════════════════════════════════

def build_overview_tab(store_id: str = "store-a"):
    data = gd.get_data(store_id)
    overview = data["compliance_overview"]
    brands = data["brand_distribution"]

    if not overview:
        store = sm.get(store_id)
        store_name = store["name"] if store else store_id
        return html.Div([
            html.Div([
                html.I(className="fas fa-store fa-3x text-muted mb-3"),
                html.H4(f"No shelf images in {store_name} yet", className="text-muted"),
                html.P(
                    "Use the Schematic Editor tab to create planogram schematics for this store. "
                    "Upload shelf images to start compliance analysis.",
                    className="text-muted",
                ),
            ], className="text-center py-5"),
        ])

    scores = [r["score"] for r in overview]
    avg_score = sum(scores) / len(scores) if scores else 0
    above_50 = sum(1 for s in scores if s >= 0.50)
    total_products = sum(r["num_products"] for r in overview)

    score_fig = go.Figure(go.Histogram(
        x=[s * 100 for s in scores], nbinsx=20, marker_color="#3b82f6",
    ))
    score_fig.add_vline(x=50, line_dash="dash", line_color="#ef4444", annotation_text="50% target")
    score_fig.update_layout(
        xaxis_title="Compliance %", yaxis_title="# Images",
        margin=dict(t=30, b=40, l=50, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=300,
    )

    top_brands = [b for b in brands if b["brand"] not in ("Unknown", "Other")][:15]
    brand_fig = px.bar(
        top_brands, x="brand", y="count",
        color="brand",
        color_discrete_map={b["brand"]: b["color"] for b in top_brands},
    )
    brand_fig.update_layout(
        showlegend=False,
        xaxis_title="", yaxis_title="Product Count",
        margin=dict(t=20, b=80, l=50, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=300,
        xaxis_tickangle=-45,
    )

    by_plano = {}
    for r in overview:
        by_plano.setdefault(r["planogram_id"], []).append(r["score"])
    plano_scores = [{"planogram": pid, "avg_score": round(sum(s) / len(s) * 100, 1)}
                    for pid, s in sorted(by_plano.items())]
    plano_fig = px.bar(
        plano_scores, x="planogram", y="avg_score", text="avg_score",
        color="avg_score", color_continuous_scale=["#ef4444", "#eab308", "#22c55e"],
        range_color=[20, 80],
    )
    plano_fig.update_layout(
        yaxis_title="Avg Compliance %", xaxis_title="Planogram",
        coloraxis_showscale=False,
        margin=dict(t=20, b=40, l=50, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=300,
    )
    plano_fig.update_traces(textposition="outside")

    table_data = sorted(overview, key=lambda r: r["score"], reverse=True)
    for r in table_data:
        r["score_pct"] = f"{r['score'] * 100:.0f}%"
        r["id_pct"] = f"{r['identified_pct']:.0f}%"
        r["issues"] = r["wrong_position"] + r["substitution"] + r["out_of_stock"]

    return html.Div([
        dbc.Row([
            kpi_card("Avg Compliance", f"{avg_score * 100:.1f}%", "chart-line", "primary"),
            kpi_card("Shelf Images", str(len(overview)), "image", "success"),
            kpi_card("Total Products", f"{total_products:,}", "boxes-stacked", "info"),
            kpi_card("Above 50%", f"{above_50}/{len(overview)}", "check-double", "warning"),
        ]),
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("Compliance Score Distribution (NW Alignment)"),
                dbc.CardBody(dcc.Graph(figure=score_fig, config={"displayModeBar": False})),
            ], className="shadow-sm border-0"), lg=4),
            dbc.Col(dbc.Card([
                dbc.CardHeader("Brand Distribution (Top 15 — Vision-Identified)"),
                dbc.CardBody(dcc.Graph(figure=brand_fig, config={"displayModeBar": False})),
            ], className="shadow-sm border-0"), lg=4),
            dbc.Col(dbc.Card([
                dbc.CardHeader("Compliance by Planogram"),
                dbc.CardBody(dcc.Graph(figure=plano_fig, config={"displayModeBar": False})),
            ], className="shadow-sm border-0"), lg=4),
        ], className="mb-4"),
        dbc.Card([
            dbc.CardHeader("All Shelf Images — Click a row to inspect"),
            dbc.CardBody(
                dash_table.DataTable(
                    id="compliance-table",
                    columns=[
                        {"name": "Image", "id": "filename"},
                        {"name": "Planogram", "id": "planogram_id"},
                        {"name": "Camera", "id": "camera"},
                        {"name": "Shelves", "id": "num_shelves"},
                        {"name": "Products", "id": "num_products"},
                        {"name": "Identified %", "id": "id_pct"},
                        {"name": "Score", "id": "score_pct"},
                        {"name": "Correct", "id": "correct"},
                        {"name": "Wrong Pos", "id": "wrong_position"},
                        {"name": "OOS", "id": "out_of_stock"},
                        {"name": "Extra", "id": "extra"},
                    ],
                    data=table_data,
                    row_selectable="single",
                    sort_action="native",
                    filter_action="native",
                    page_size=15,
                    style_table={"overflowX": "auto"},
                    style_cell={"textAlign": "left", "padding": "8px", "fontSize": "0.85rem"},
                    style_header={"fontWeight": "bold", "backgroundColor": "#f8f9fa"},
                    style_data_conditional=[
                        {"if": {"filter_query": "{score} >= 0.5"}, "backgroundColor": "#f0fdf4"},
                        {"if": {"filter_query": "{score} < 0.3"}, "backgroundColor": "#fef2f2"},
                    ],
                ),
            ),
        ], className="shadow-sm border-0"),
    ])


# ═══════════════════════════════════════════════════════════════════
# TAB 2 — SHELF INSPECTOR
# ═══════════════════════════════════════════════════════════════════

def _schematic_options(store_id: str | None = None):
    import planogram_store as ps
    opts = []
    if store_id and store_id != "store-a":
        keys = ps.list_store_keys(store_id)
    else:
        keys = ps.list_keys()
    for info in keys:
        origin_tag = " [custom]" if info["origin"] == "custom" else ""
        label = f"{info['key']} — {info['total_products']}p, {info['num_rows']}r{origin_tag}"
        opts.append({"label": label, "value": info["key"]})
    return opts


def build_shelf_selector(store_id: str = "store-a"):
    data = gd.get_data(store_id)
    if not data["shelves"]:
        store = sm.get(store_id)
        store_name = store["name"] if store else store_id
        return html.Div([
            html.Div([
                html.I(className="fas fa-camera fa-3x text-muted mb-3"),
                html.H4(f"No shelf images in {store_name}", className="text-muted"),
                html.P(
                    "The Shelf Inspector requires shelf images. Create schematics in the "
                    "Schematic Editor tab to define planograms for this store.",
                    className="text-muted",
                ),
            ], className="text-center py-5"),
        ])
    img_options = [{"label": s.filename, "value": s.filename} for s in data["shelves"]]
    schema_options = _schematic_options(store_id)
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("Select Shelf Image", className="fw-bold mb-1"),
                dcc.Dropdown(id="shelf-selector", options=img_options,
                             value=img_options[0]["value"] if img_options else None, clearable=False),
            ], lg=4),
            dbc.Col([
                html.Label("Compare Against Schematic", className="fw-bold mb-1"),
                dcc.Dropdown(id="schematic-selector", options=schema_options,
                             placeholder="Auto-match (default)", clearable=True),
            ], lg=4),
            dbc.Col(id="shelf-kpis", lg=4),
        ], className="mb-3"),
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-camera me-2"),
                    "Actual Shelf Photo",
                ]),
                dbc.CardBody(
                    html.Div(id="shelf-photo-container", style={
                        "textAlign": "center", "backgroundColor": "#0f172a",
                        "borderRadius": "4px", "padding": "8px", "minHeight": "300px",
                    }),
                ),
            ], className="shadow-sm border-0"), lg=4),
            dbc.Col(dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-vector-square me-2"),
                    "Detected Layout (bounding boxes)",
                ]),
                dbc.CardBody(dcc.Graph(id="shelf-image-graph", config={"displayModeBar": True})),
            ], className="shadow-sm border-0"), lg=4),
            dbc.Col(dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-th me-2"),
                    "Schematic Reference",
                ]),
                dbc.CardBody([
                    html.Div(id="schematic-ref-label", className="small text-muted mb-1"),
                    dcc.Graph(id="schematic-graph", config={"displayModeBar": True}),
                    html.Div([
                        html.Label("Crop: select column range to compare", className="small fw-bold mt-2"),
                        dcc.RangeSlider(
                            id="crop-range-slider", min=1, max=30, step=1, value=[1, 30],
                            marks=None, tooltip={"placement": "bottom", "always_visible": True},
                        ),
                    ], id="crop-slider-container", style={"display": "none"}),
                ]),
            ], className="shadow-sm border-0"), lg=4),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-eye me-2"),
                    "Preview Compliance",
                    dbc.Badge("UNCOMMITTED", id="preview-badge", color="warning",
                              className="ms-2", style={"display": "none"}),
                ]),
                dbc.CardBody([
                    html.Div(id="preview-compliance", className="mb-2"),
                    html.Div([
                        dbc.Button([html.I(className="fas fa-check me-1"), "Commit Score"],
                                   id="commit-crop-btn", color="success", size="sm", className="me-2",
                                   style={"display": "none"}),
                        dbc.Button([html.I(className="fas fa-undo me-1"), "Reset Crop"],
                                   id="reset-crop-btn", color="secondary", size="sm", outline=True,
                                   style={"display": "none"}),
                    ]),
                    html.Div(id="commit-status"),
                ]),
            ], className="shadow-sm border-0"), lg=4),
            dbc.Col(dbc.Card([
                dbc.CardHeader("Row-by-Row Alignment (Needleman-Wunsch)"),
                dbc.CardBody(id="alignment-details", style={"maxHeight": "500px", "overflowY": "auto"}),
            ], className="shadow-sm border-0"), lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Brand Legend"),
                    dbc.CardBody(id="brand-legend"),
                ], className="shadow-sm border-0 mb-3"),
                dbc.Card([
                    dbc.CardHeader("Compliance Summary (Full Reference)"),
                    dbc.CardBody(id="compliance-details"),
                ], className="shadow-sm border-0"),
            ], lg=4),
        ]),

        dcc.Store(id="current-crop-state", data=None),
    ])


def build_shelf_figure(shelf: gd.ShelfImage) -> go.Figure:
    if not shelf.products:
        return go.Figure()

    all_x = [p.x + p.w for p in shelf.products] + [p.x for p in shelf.products]
    all_y = [p.y + p.h for p in shelf.products] + [p.y for p in shelf.products]
    max_x = max(all_x) + 50
    max_y = max(all_y) + 50

    fig = go.Figure()

    for p in shelf.products:
        color = p.color
        fig.add_shape(
            type="rect",
            x0=p.x, y0=p.y, x1=p.x + p.w, y1=p.y + p.h,
            line=dict(color=color, width=2),
            fillcolor=color, opacity=0.3,
        )
        fig.add_annotation(
            x=p.center_x, y=p.y - 10,
            text=f"<b>{p.brand}</b>",
            showarrow=False,
            font=dict(size=9, color=color),
        )

    fig.update_xaxes(range=[0, max_x], showgrid=False, zeroline=False)
    fig.update_yaxes(range=[max_y, 0], showgrid=False, zeroline=False, scaleanchor="x")
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="#1e293b", plot_bgcolor="#1e293b",
        height=400, dragmode="pan",
    )
    return fig


def build_schematic_figure(schematic: pe.SchematicPlanogram, highlight_range: tuple | None = None) -> go.Figure:
    """Render a schematic planogram as colored blocks in a grid layout.

    highlight_range: optional (col_start, col_end) 1-based inclusive range.
    Columns outside this range are dimmed to show the active crop.
    """
    fig = go.Figure()
    if not schematic or not schematic.rows:
        return fig

    box_w, box_h = 80, 50
    gap_x, gap_y = 8, 16
    pad_left, pad_top = 60, 20

    max_cols = max(len(r.brands) for r in schematic.rows) if schematic.rows else 0

    for row_idx, row in enumerate(schematic.rows):
        y0 = pad_top + row_idx * (box_h + gap_y)
        fig.add_annotation(
            x=pad_left - 10, y=y0 + box_h / 2,
            text=f"<b>R{row_idx + 1}</b>", showarrow=False,
            font=dict(size=11, color="#e2e8f0"), xanchor="right",
        )
        for col_idx, brand in enumerate(row.brands):
            x0 = pad_left + col_idx * (box_w + gap_x)
            color = gd.BRAND_COLORS.get(brand, "#94a3b8")

            in_range = True
            if highlight_range:
                col_1based = col_idx + 1
                in_range = highlight_range[0] <= col_1based <= highlight_range[1]

            opacity = 0.4 if in_range else 0.08
            line_w = 2 if in_range else 1
            line_color = color if in_range else "#334155"

            fig.add_shape(
                type="rect", x0=x0, y0=y0, x1=x0 + box_w, y1=y0 + box_h,
                line=dict(color=line_color, width=line_w), fillcolor=color, opacity=opacity,
            )
            label = brand[:8] + ".." if len(brand) > 10 else brand
            font_color = "white" if in_range else "#475569"
            fig.add_annotation(
                x=x0 + box_w / 2, y=y0 + box_h / 2,
                text=f"<b>{label}</b>", showarrow=False,
                font=dict(size=7, color=font_color),
            )

    total_w = pad_left + max_cols * (box_w + gap_x) + 40
    total_h = pad_top + len(schematic.rows) * (box_h + gap_y) + 20

    fig.update_xaxes(range=[0, total_w], showgrid=False, zeroline=False, showticklabels=False)
    fig.update_yaxes(range=[total_h, 0], showgrid=False, zeroline=False, showticklabels=False)
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="#0f172a", plot_bgcolor="#0f172a",
        height=400,
    )
    return fig


def build_alignment_view(result: pe.ShelfComplianceResult) -> list:
    """Build HTML rendering of the row-by-row NW alignment."""
    STATUS_COLOR = {
        "Correct": "#22c55e",
        "Wrong Position": "#eab308",
        "Substitution": "#f97316",
        "Out-of-Stock": "#ef4444",
        "Extra": "#3b82f6",
    }

    sections = []
    for rr in result.row_results:
        row_pct = f"{rr.score * 100:.0f}%"
        row_color = "success" if rr.score >= 0.5 else ("warning" if rr.score >= 0.3 else "danger")

        header = html.Div([
            html.Strong(f"Row {rr.row_index + 1}", className="me-2"),
            dbc.Badge(row_pct, color=row_color, className="me-2"),
            html.Small(
                f"{len(rr.reference_brands)} expected, {len(rr.detected_brands)} detected",
                className="text-muted",
            ),
        ], className="mb-2")

        alignment_boxes = []
        for a in rr.aligned:
            bg_color = STATUS_COLOR.get(a.status, "#64748b")
            exp_text = a.expected_display
            det_text = a.detected_display
            alignment_boxes.append(html.Div([
                html.Div(exp_text, style={
                    "fontSize": "0.65rem", "color": "#94a3b8", "whiteSpace": "nowrap",
                    "overflow": "hidden", "textOverflow": "ellipsis", "maxWidth": "70px",
                }),
                html.Div("↕", style={"fontSize": "0.6rem", "color": "#475569"}),
                html.Div(det_text, style={
                    "fontSize": "0.65rem", "color": "white", "fontWeight": "bold",
                    "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis",
                    "maxWidth": "70px",
                }),
            ], style={
                "display": "inline-flex", "flexDirection": "column", "alignItems": "center",
                "border": f"2px solid {bg_color}", "borderRadius": "4px",
                "padding": "2px 4px", "margin": "2px", "minWidth": "60px",
                "backgroundColor": f"{bg_color}22", "textAlign": "center",
            }, title=f"{a.expected_display} → {a.detected_display} ({a.status})"))

        sections.append(html.Div([
            header,
            html.Div(alignment_boxes, style={"display": "flex", "flexWrap": "wrap"}),
            html.Hr(className="my-2"),
        ]))

    return sections


def _build_photo_element(filename: str):
    """Build an <img> element for the shelf photo, loading from the UC Volume via SDK."""
    b64 = _read_volume_image(filename)
    if b64:
        return html.Img(
            src=f"data:image/jpeg;base64,{b64}",
            style={"maxWidth": "100%", "maxHeight": "380px", "objectFit": "contain",
                   "borderRadius": "4px"},
            alt=filename,
        )
    return html.Div([
        html.I(className="fas fa-image fa-3x text-muted mb-2"),
        html.P(filename, className="text-muted small mb-1"),
        html.P(
            "Could not load photo from UC Volume. Check app permissions.",
            className="text-muted small fst-italic",
        ),
    ], className="text-center", style={"paddingTop": "60px"})


# ═══════════════════════════════════════════════════════════════════
# TAB 3 — SCHEMATIC EDITOR
# ═══════════════════════════════════════════════════════════════════

BRAND_OPTIONS = sorted(gd.BRAND_COLORS.keys())


def build_editor_tab(store_id: str = "store-a"):
    import planogram_store as ps
    schema_options = _schematic_options(store_id)

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.H5("Schematic Planogram Editor", className="mb-2"),
                html.P(
                    "Select a schematic to view or edit. Auto-generated schematics come from "
                    "multi-image consensus. You can edit any schematic or create new custom ones.",
                    className="text-muted small",
                ),
            ], lg=8),
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button([html.I(className="fas fa-plus me-1"), "New"],
                               id="editor-new-btn", color="success", size="sm"),
                    dbc.Button([html.I(className="fas fa-clone me-1"), "Clone"],
                               id="editor-clone-btn", color="info", size="sm"),
                    dbc.Button([html.I(className="fas fa-trash me-1"), "Delete"],
                               id="editor-delete-btn", color="danger", size="sm", outline=True),
                ], className="float-end"),
            ], lg=4),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col([
                html.Label("Select Schematic", className="fw-bold mb-1"),
                dcc.Dropdown(id="editor-schematic-select", options=schema_options,
                             value=schema_options[0]["value"] if schema_options else None,
                             clearable=False),
            ], lg=4),
            dbc.Col(id="editor-meta", lg=8),
        ], className="mb-3"),

        dbc.Card([
            dbc.CardHeader([
                html.I(className="fas fa-th me-2"),
                html.Span("Schematic Preview", id="editor-preview-label"),
            ]),
            dbc.CardBody(dcc.Graph(id="editor-preview-graph", config={"displayModeBar": False})),
        ], className="shadow-sm border-0 mb-3"),

        dbc.Card([
            dbc.CardHeader([
                html.I(className="fas fa-edit me-2"),
                "Edit Row Brand Sequences",
                html.Small(
                    " — one brand per line, use pipe (|) to separate positions",
                    className="text-muted ms-2",
                ),
            ]),
            dbc.CardBody(id="editor-rows-container"),
        ], className="shadow-sm border-0 mb-3"),

        dbc.Row([
            dbc.Col([
                dbc.Button([html.I(className="fas fa-save me-2"), "Save Changes"],
                           id="editor-save-btn", color="primary", className="me-2"),
                dbc.Button([html.I(className="fas fa-undo me-2"), "Reset to Auto"],
                           id="editor-reset-btn", color="secondary", outline=True),
            ]),
            dbc.Col(html.Div(id="editor-status"), lg=6),
        ], className="mb-3"),

        html.Hr(),

        dbc.Card([
            dbc.CardHeader([
                html.I(className="fas fa-robot me-2"),
                "Create Schematic from Image (AI Brand Detection)",
            ]),
            dbc.CardBody([
                html.P(
                    "Upload a shelf image and AI will detect brands to pre-populate a new schematic. "
                    "Review and edit the detected brands before saving.",
                    className="text-muted small mb-3",
                ),
                dbc.Row([
                    dbc.Col([
                        dcc.Upload(
                            id="ai-image-upload",
                            children=html.Div([
                                html.I(className="fas fa-cloud-upload-alt fa-2x text-primary mb-2"),
                                html.P("Drag & drop or click to upload a shelf image",
                                       className="text-muted small mb-0"),
                                html.P("Supports JPG, PNG", className="text-muted small"),
                            ], className="text-center py-4"),
                            style={
                                "border": "2px dashed #ced4da", "borderRadius": "8px",
                                "cursor": "pointer", "backgroundColor": "#f8f9fa",
                            },
                            accept="image/*",
                        ),
                        html.Div(id="ai-upload-preview", className="mt-2"),
                    ], lg=4),
                    dbc.Col([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Schematic Key", className="fw-bold"),
                                dbc.Input(id="ai-schema-key", placeholder="P10/3s/R1", type="text"),
                            ], lg=6),
                            dbc.Col([
                                dbc.Label("Number of Shelf Rows", className="fw-bold"),
                                dbc.Input(id="ai-num-rows", type="number", value=3, min=1, max=10),
                            ], lg=6),
                        ], className="mb-3"),
                        html.Div(id="ai-detect-btn-container", children=[
                            dbc.Button(
                                [html.I(className="fas fa-magic me-2"), "Detect Brands with AI"],
                                id="ai-detect-btn", color="primary", disabled=True,
                            ),
                        ]),
                        html.Div(id="ai-processing-status", className="mt-2"),
                        dcc.Loading(
                            html.Div(id="ai-detect-result", className="mt-3"),
                            type="default",
                            overlay_style={"visibility": "visible", "opacity": 0.7,
                                           "backgroundColor": "white"},
                            custom_spinner=html.Div([
                                dbc.Spinner(color="primary", size="lg"),
                                html.P("Analyzing shelf image with AI...",
                                       className="text-primary fw-bold mt-3 mb-0"),
                                html.P("Identifying brands using Foundation Model API — this may take 10-30 seconds",
                                       className="text-muted small"),
                            ], className="text-center py-4"),
                            target_components={"ai-detect-result": "children"},
                        ),
                    ], lg=8),
                ]),
            ]),
        ], className="shadow-sm border-0 mb-3"),

        dbc.Modal([
            dbc.ModalHeader("Create New Schematic"),
            dbc.ModalBody([
                dbc.Label("Schematic Key (format: P01/3s/R1)"),
                dbc.Input(id="new-schema-key", placeholder="P01/3s/R1", type="text"),
                dbc.Label("Number of shelf rows", className="mt-2"),
                dbc.Input(id="new-schema-rows", type="number", value=3, min=1, max=10),
                dbc.Label("Products per row", className="mt-2"),
                dbc.Input(id="new-schema-cols", type="number", value=10, min=1, max=30),
            ]),
            dbc.ModalFooter([
                dbc.Button("Create", id="new-schema-create-btn", color="success"),
                dbc.Button("Cancel", id="new-schema-cancel-btn", color="secondary", outline=True),
            ]),
        ], id="new-schema-modal", is_open=False),
    ])


# ═══════════════════════════════════════════════════════════════════
# TAB 4 — DATASET INFO
# ═══════════════════════════════════════════════════════════════════

def build_dataset_tab(store_id: str = "store-a"):
    data = gd.get_data(store_id)
    shelves = data["shelves"]
    if not shelves:
        store = sm.get(store_id)
        store_name = store["name"] if store else store_id
        return html.Div([
            html.Div([
                html.I(className="fas fa-database fa-3x text-muted mb-3"),
                html.H4(f"No dataset for {store_name}", className="text-muted"),
                html.P(
                    "This store does not have shelf image data. The bundled Grocery Dataset "
                    "is only available for Store A.",
                    className="text-muted",
                ),
            ], className="text-center py-5"),
        ])
    total_products = sum(s.num_products for s in shelves)
    cameras = set(s.camera_id for s in shelves)
    planograms = set(s.planogram_id for s in shelves)
    brands_dist = data["brand_distribution"]
    identified = sum(b["count"] for b in brands_dist if b["brand"] not in ("Unknown", "Other"))
    id_pct = round(identified / total_products * 100, 1)

    return html.Div([
        dbc.Row([
            kpi_card("Shelf Images", str(len(shelves)), "images", "primary"),
            kpi_card("Total Products", f"{total_products:,}", "box", "success"),
            kpi_card("Brands Identified", f"{id_pct}%", "eye", "info"),
            kpi_card("Unique Brands", str(len([b for b in brands_dist if b["brand"] not in ("Unknown", "Other")])), "tags", "warning"),
        ], className="mb-4"),
        dbc.Card([
            dbc.CardHeader("About the Dataset & Brand Identification"),
            dbc.CardBody([
                dcc.Markdown(f"""
**Grocery Dataset** — *Varol & Kuzu, "Toward Retail Product Recognition on Grocery Shelves", ICIVC 2014*

- Collected from ~40 grocery stores in Istanbul, Turkey (Spring 2014)
- 4 cameras: iPhone 5S, iPhone 4, Sony Cybershot, Nikon Coolpix
- **354 shelf images** with **{total_products:,} annotated product bounding boxes**
- Source: [github.com/gulvarol/grocerydataset](https://github.com/gulvarol/grocerydataset)

**Brand Identification Pipeline** (Databricks Foundation Model API):
1. Original dataset only labeled 10 categories (brands 1-10), leaving **79% as "category 0" (unclassified)**
2. Used `ai_query('databricks-claude-haiku-4-5', ..., files => ...)` to identify brands from cropped product images
3. Triple-validated the 10 original categories from `BrandImages/` — 100% consistent
4. Batch-classified all **10,440 "category 0" products** from `ProductImagesFromShelves/0/`
5. Normalized spelling variants (374 raw labels → {len([b for b in brands_dist if b["brand"] not in ("Unknown", "Other")])} canonical brands)
6. Result: **{id_pct}% of products now have identified brand names**

**Volume location:** `/Volumes/serverless_stable_wunnava_catalog/planobricks_reference/inputs/images/`

**Delta Tables:**
- `planobricks_reference.brand_mapping` — Original 10-category mapping
- `planobricks_reference.product_reclassification` — Raw vision model outputs (10,440 rows)
- `planobricks_reference.enriched_products` — Normalized brand per product with shelf coordinates
"""),
            ]),
        ], className="shadow-sm border-0"),
    ])


# ═══════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════

sm.init()


def _store_dropdown_options():
    return [{"label": s["name"], "value": s["id"]} for s in sm.list_stores()]


navbar = dbc.Navbar(
    dbc.Container([
        dbc.NavbarBrand([
            html.I(className="fas fa-cubes me-2"), "PlanoBricks",
        ], className="fw-bold fs-4"),
        html.Div([
            html.Div([
                html.I(className="fas fa-store text-light me-2", style={"fontSize": "0.9rem"}),
                dcc.Dropdown(
                    id="store-selector",
                    options=_store_dropdown_options(),
                    value="store-a",
                    clearable=False,
                    style={"width": "200px", "fontSize": "0.85rem"},
                    className="d-inline-block",
                ),
                dbc.Button(
                    [html.I(className="fas fa-plus")],
                    id="open-store-modal-btn", color="light", size="sm",
                    outline=True, className="ms-2",
                    title="Create new store",
                ),
            ], className="d-flex align-items-center me-3"),
            dbc.Badge("AI-identified brands", color="info", className="me-2"),
            html.Small("Planogram Compliance", className="text-light"),
        ], className="d-flex align-items-center"),
    ], fluid=True),
    color="dark", dark=True, className="mb-4 shadow",
)

app.layout = html.Div([
    navbar,
    dbc.Container([
        html.Div(id="store-info-banner", className="mb-3"),
        dbc.Tabs([
            dbc.Tab(label="Compliance Overview", tab_id="tab-overview",
                    children=html.Div(id="overview-container", children=build_overview_tab())),
            dbc.Tab(label="Shelf Inspector", tab_id="tab-inspector",
                    children=build_shelf_selector()),
            dbc.Tab(label="Schematic Editor", tab_id="tab-editor",
                    children=build_editor_tab()),
            dbc.Tab(label="Dataset", tab_id="tab-dataset",
                    children=html.Div(id="dataset-container", children=build_dataset_tab())),
        ], id="main-tabs", active_tab="tab-overview"),
    ], fluid=True, className="px-4 pb-4"),

    dcc.Store(id="active-store-id", data="store-a"),

    dbc.Modal([
        dbc.ModalHeader("Create New Store"),
        dbc.ModalBody([
            dbc.Label("Store Name"),
            dbc.Input(id="new-store-name", placeholder="e.g. Store B", type="text"),
            dbc.Label("Description (optional)", className="mt-2"),
            dbc.Textarea(id="new-store-desc", placeholder="Describe this store location or purpose", rows=2),
        ]),
        dbc.ModalFooter([
            dbc.Button("Create Store", id="create-store-btn", color="success"),
            dbc.Button("Cancel", id="cancel-store-btn", color="secondary", outline=True),
        ]),
    ], id="store-modal", is_open=False),
])


# ═══════════════════════════════════════════════════════════════════
# CALLBACKS — Store Management
# ═══════════════════════════════════════════════════════════════════

@callback(
    Output("active-store-id", "data"),
    Input("store-selector", "value"),
)
def sync_store(store_id):
    if store_id:
        gd.set_current_store(store_id)
    return store_id or "store-a"


@callback(
    Output("store-modal", "is_open"),
    Input("open-store-modal-btn", "n_clicks"),
    Input("cancel-store-btn", "n_clicks"),
    Input("create-store-btn", "n_clicks"),
    State("store-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_store_modal(open_click, cancel_click, create_click, is_open):
    return not is_open


@callback(
    Output("store-selector", "options"),
    Output("store-selector", "value"),
    Input("create-store-btn", "n_clicks"),
    State("new-store-name", "value"),
    State("new-store-desc", "value"),
    State("store-selector", "value"),
    prevent_initial_call=True,
)
def create_store(n_clicks, name, desc, current):
    if not n_clicks or not name or not name.strip():
        return dash.no_update, dash.no_update
    store = sm.create(name.strip(), (desc or "").strip())
    return _store_dropdown_options(), store["id"]


@callback(
    Output("store-info-banner", "children"),
    Output("overview-container", "children"),
    Output("dataset-container", "children"),
    Output("shelf-selector", "options", allow_duplicate=True),
    Output("shelf-selector", "value", allow_duplicate=True),
    Output("schematic-selector", "options", allow_duplicate=True),
    Output("editor-schematic-select", "options", allow_duplicate=True),
    Output("editor-schematic-select", "value", allow_duplicate=True),
    Input("active-store-id", "data"),
    prevent_initial_call=True,
)
def on_store_changed(store_id):
    """Update all store-dependent components when the active store changes."""
    store_id = store_id or "store-a"
    store = sm.get(store_id)

    # Banner
    if store:
        data = gd.get_data(store_id)
        n_images = len(data["shelves"])
        n_schematics = len(data.get("schematics", {}))
        badges = []
        if n_images:
            badges.append(dbc.Badge(f"{n_images} shelf images", color="light", text_color="dark", className="me-2"))
        badges.append(dbc.Badge(f"{n_schematics} schematics", color="light", text_color="dark", className="me-2"))
        banner = dbc.Alert([
            html.I(className="fas fa-store me-2"),
            html.Strong(store["name"], className="me-2"),
            html.Span(f"— {store.get('description', '')}", className="text-muted me-3"),
            *badges,
        ], color="light", className="py-2 mb-0 border-0 shadow-sm")
    else:
        banner = ""

    # Overview + Dataset (full re-render)
    overview = build_overview_tab(store_id)
    dataset = build_dataset_tab(store_id)

    # Inspector dropdowns
    data = gd.get_data(store_id)
    img_options = [{"label": s.filename, "value": s.filename} for s in data["shelves"]]
    img_value = img_options[0]["value"] if img_options else None
    schema_options = _schematic_options(store_id)

    # Editor dropdown
    editor_opts = _schematic_options(store_id)
    editor_val = editor_opts[0]["value"] if editor_opts else None

    return banner, overview, dataset, img_options, img_value, schema_options, editor_opts, editor_val


# ═══════════════════════════════════════════════════════════════════
# CALLBACKS — Inspector
# ═══════════════════════════════════════════════════════════════════

@callback(
    Output("shelf-selector", "value"),
    Input("compliance-table", "selected_rows"),
    State("compliance-table", "data"),
    prevent_initial_call=True,
)
def table_row_to_selector(selected_rows, table_data):
    if selected_rows and table_data:
        return table_data[selected_rows[0]]["filename"]
    return dash.no_update


@callback(
    Output("schematic-selector", "value"),
    Input("shelf-selector", "value"),
    State("schematic-selector", "value"),
)
def auto_match_schematic(filename, current_schema):
    """When a new image is selected, auto-match the schematic (unless user overrode)."""
    if not filename:
        return dash.no_update
    data = gd.get_data()
    shelf = data["shelf_map"].get(filename)
    if not shelf:
        return dash.no_update
    import planogram_store as ps
    auto_key = ps._key_str((shelf.planogram_id, shelf.num_shelves, shelf.shelf_rank))
    return auto_key


@callback(
    Output("shelf-photo-container", "children"),
    Output("shelf-image-graph", "figure"),
    Output("schematic-graph", "figure"),
    Output("schematic-ref-label", "children"),
    Output("shelf-kpis", "children"),
    Output("brand-legend", "children"),
    Output("compliance-details", "children"),
    Output("alignment-details", "children"),
    Input("shelf-selector", "value"),
    Input("schematic-selector", "value"),
)
def update_shelf_inspector(filename, schema_key):
    import planogram_store as ps
    empty = go.Figure()
    no_photo = html.P("No image available", className="text-muted text-center mt-5")
    defaults = (no_photo, empty, empty, "Schematic Reference", "", "", "", "")
    if not filename:
        return defaults

    data = gd.get_data()
    shelf = data["shelf_map"].get(filename)
    if not shelf:
        return defaults

    if schema_key:
        schematic = ps.get(schema_key)
        ref_label = f"Reference: {schema_key}"
    else:
        auto_key = (shelf.planogram_id, shelf.num_shelves, shelf.shelf_rank)
        schematic = data["schematics"].get(auto_key)
        ref_label = f"Reference: {ps._key_str(auto_key)} (auto)"

    cr = _compute_live(shelf, schematic)

    photo_el = _build_photo_element(filename)
    fig = build_shelf_figure(shelf)
    schematic_fig = build_schematic_figure(schematic) if schematic else go.Figure()

    score = cr.score if cr else 0.0
    kpis = dbc.Row([
        kpi_card("Score", f"{score * 100:.0f}%", "bullseye",
                 "success" if score >= 0.5 else ("warning" if score >= 0.3 else "danger")),
        kpi_card("Products", str(shelf.num_products), "box", "info"),
        kpi_card("Identified", f"{shelf.identified_pct:.0f}%", "eye", "success"),
        kpi_card("Out-of-Stock", str(cr.out_of_stock) if cr else "0", "times-circle", "danger"),
    ])

    brand_counts = shelf.brand_counts
    legend_items = []
    for brand in sorted(brand_counts.keys(), key=lambda b: brand_counts[b], reverse=True):
        color = gd.BRAND_COLORS.get(brand, "#94a3b8")
        count = brand_counts[brand]
        legend_items.append(html.Div([
            html.Span("■ ", style={"color": color, "fontSize": "1.2rem"}),
            html.Span(f"{brand} ", className="fw-bold"),
            dbc.Badge(str(count), color="light", text_color="dark"),
        ], className="mb-1"))

    compliance_summary = html.Div()
    if cr:
        compliance_summary = html.Div([
            html.Div([
                html.Span("Correct: ", className="fw-bold"),
                dbc.Badge(str(cr.correct), color="success", className="me-2"),
            ], className="mb-1"),
            html.Div([
                html.Span("Wrong Position: ", className="fw-bold"),
                dbc.Badge(str(cr.wrong_position), color="warning", className="me-2"),
            ], className="mb-1"),
            html.Div([
                html.Span("Substitution: ", className="fw-bold"),
                dbc.Badge(str(cr.substitution), color="info", className="me-2"),
            ], className="mb-1"),
            html.Div([
                html.Span("Out-of-Stock: ", className="fw-bold"),
                dbc.Badge(str(cr.out_of_stock), color="danger", className="me-2"),
            ], className="mb-1"),
            html.Div([
                html.Span("Extra: ", className="fw-bold"),
                dbc.Badge(str(cr.extra), color="primary", className="me-2"),
            ], className="mb-1"),
            html.Hr(className="my-2"),
            html.Small(
                f"{ref_label} ({schematic.total_products} products)" if schematic else "No reference",
                className="text-muted",
            ),
        ])

    alignment_view = build_alignment_view(cr) if cr else [html.P("No alignment data", className="text-muted")]

    return photo_el, fig, schematic_fig, ref_label, kpis, legend_items, compliance_summary, alignment_view


@callback(
    Output("crop-range-slider", "min"),
    Output("crop-range-slider", "max"),
    Output("crop-range-slider", "value"),
    Output("crop-slider-container", "style"),
    Output("current-crop-state", "data"),
    Output("preview-compliance", "children"),
    Output("preview-badge", "style"),
    Output("commit-crop-btn", "style"),
    Output("reset-crop-btn", "style"),
    Output("commit-status", "children"),
    Input("shelf-selector", "value"),
    Input("schematic-selector", "value"),
)
def init_crop_controls(filename, schema_key):
    """Initialize the crop slider and preview panel when a shelf/schematic is selected."""
    import planogram_store as ps
    hidden = {"display": "none"}
    defaults = (1, 30, [1, 30], hidden, None, "", hidden, hidden, hidden, "")
    if not filename:
        return defaults

    data = gd.get_data()
    shelf = data["shelf_map"].get(filename)
    if not shelf:
        return defaults

    if schema_key:
        schematic = ps.get(schema_key)
    else:
        auto_key = (shelf.planogram_id, shelf.num_shelves, shelf.shelf_rank)
        schematic = data["schematics"].get(auto_key)

    max_cols = 1
    if schematic and schematic.rows:
        max_cols = max(len(r.brands) for r in schematic.rows)
    slider_style = {} if schematic and max_cols > 1 else hidden

    crop_state = {"filename": filename, "schema_key": schema_key or "",
                  "max_cols": max_cols, "crop_start": 1, "crop_end": max_cols,
                  "committed": True}

    initial_preview = html.Div([
        html.Small("Full schematic selected — use the crop slider above to narrow the comparison range.",
                   className="text-muted"),
    ])

    return 1, max_cols, [1, max_cols], slider_style, crop_state, initial_preview, hidden, hidden, hidden, ""


def _compute_live(shelf, schematic):
    """Compute compliance for a single image against a specific schematic."""
    if not schematic:
        return pe.ShelfComplianceResult(
            filename=shelf.filename, planogram_id=shelf.planogram_id,
            num_shelves=shelf.num_shelves, score=0.0,
            total_products=shelf.num_products,
            correct=0, wrong_position=0, substitution=0, out_of_stock=0, extra=0,
        )
    detected_rows = pe.cluster_into_rows(shelf.products)
    num_rows = len(schematic.rows)
    if len(detected_rows) < num_rows:
        detected_rows.extend([] for _ in range(num_rows - len(detected_rows)))

    all_aligned = []
    row_results = []
    for i in range(num_rows):
        ref_brands = schematic.rows[i].brands
        det_brands = pe.row_brand_sequence(detected_rows[i]) if i < len(detected_rows) else []
        aligned = pe.needleman_wunsch(ref_brands, det_brands)
        row_score = pe.alignment_score(aligned)
        all_aligned.extend(aligned)
        row_results.append(pe.RowComplianceResult(
            row_index=i, reference_brands=ref_brands, detected_brands=det_brands,
            aligned=aligned, score=round(row_score, 3),
        ))

    total_correct = sum(1 for a in all_aligned if a.status == "Correct")
    total_expected = sum(1 for a in all_aligned if a.expected is not None)
    return pe.ShelfComplianceResult(
        filename=shelf.filename, planogram_id=shelf.planogram_id,
        num_shelves=shelf.num_shelves,
        score=round(total_correct / total_expected, 3) if total_expected else 0.0,
        total_products=shelf.num_products,
        correct=total_correct,
        wrong_position=sum(1 for a in all_aligned if a.status == "Wrong Position"),
        substitution=sum(1 for a in all_aligned if a.status == "Substitution"),
        out_of_stock=sum(1 for a in all_aligned if a.status == "Out-of-Stock"),
        extra=sum(1 for a in all_aligned if a.status == "Extra"),
        row_results=row_results, aligned_pairs=all_aligned,
    )


def _crop_schematic(schematic: pe.SchematicPlanogram, col_start: int, col_end: int) -> pe.SchematicPlanogram:
    """Return a shallow copy of the schematic with each row sliced to [col_start, col_end] (1-based)."""
    cropped_rows = []
    for row in schematic.rows:
        s = max(0, col_start - 1)
        e = min(len(row.brands), col_end)
        cropped_rows.append(pe.SchematicRow(
            row_index=row.row_index,
            brands=row.brands[s:e],
            avg_y=row.avg_y,
        ))
    return pe.SchematicPlanogram(
        planogram_id=schematic.planogram_id,
        num_shelves=schematic.num_shelves,
        shelf_rank=schematic.shelf_rank,
        rows=cropped_rows,
        source_images=schematic.source_images,
    )


def _build_preview_summary(cr, crop_start, crop_end, max_cols):
    """Build the preview compliance UI block for a cropped evaluation."""
    is_full = (crop_start <= 1 and crop_end >= max_cols)
    score = cr.score if cr else 0.0
    score_color = "success" if score >= 0.5 else ("warning" if score >= 0.3 else "danger")
    range_label = "Full schematic" if is_full else f"Columns {crop_start}–{crop_end} of {max_cols}"

    items = []
    items.append(html.Div([
        html.Span("Score: ", className="fw-bold"),
        dbc.Badge(f"{score * 100:.0f}%", color=score_color, className="me-2 fs-6"),
        html.Small(f"({range_label})", className="text-muted"),
    ], className="mb-2"))
    if cr:
        for label, val, color in [
            ("Correct", cr.correct, "success"), ("Wrong Position", cr.wrong_position, "warning"),
            ("Substitution", cr.substitution, "info"), ("Out-of-Stock", cr.out_of_stock, "danger"),
            ("Extra", cr.extra, "primary"),
        ]:
            items.append(html.Div([
                html.Span(f"{label}: ", className="fw-bold"),
                dbc.Badge(str(val), color=color, className="me-1"),
            ], className="mb-1", style={"fontSize": "0.9rem"}))
    return html.Div(items)


@callback(
    Output("preview-compliance", "children", allow_duplicate=True),
    Output("preview-badge", "style", allow_duplicate=True),
    Output("commit-crop-btn", "style", allow_duplicate=True),
    Output("reset-crop-btn", "style", allow_duplicate=True),
    Output("current-crop-state", "data", allow_duplicate=True),
    Output("schematic-graph", "figure", allow_duplicate=True),
    Input("crop-range-slider", "value"),
    State("shelf-selector", "value"),
    State("schematic-selector", "value"),
    State("current-crop-state", "data"),
    prevent_initial_call=True,
)
def update_crop_preview(crop_range, filename, schema_key, crop_state):
    import planogram_store as ps
    hidden = {"display": "none"}
    shown = {"display": "inline-block"}

    if not filename or not crop_state:
        return "", hidden, hidden, hidden, dash.no_update, dash.no_update

    data = gd.get_data()
    shelf = data["shelf_map"].get(filename)
    if not shelf:
        return "", hidden, hidden, hidden, dash.no_update, dash.no_update

    if schema_key:
        schematic = ps.get(schema_key)
    else:
        auto_key = (shelf.planogram_id, shelf.num_shelves, shelf.shelf_rank)
        schematic = data["schematics"].get(auto_key)

    if not schematic:
        return "", hidden, hidden, hidden, dash.no_update, dash.no_update

    max_cols = max(len(r.brands) for r in schematic.rows) if schematic.rows else 1
    crop_start, crop_end = crop_range
    is_full = (crop_start <= 1 and crop_end >= max_cols)

    cropped = _crop_schematic(schematic, crop_start, crop_end) if not is_full else schematic
    cr = _compute_live(shelf, cropped)

    preview = _build_preview_summary(cr, crop_start, crop_end, max_cols)
    badge_style = hidden if is_full else shown
    btn_style = hidden if is_full else shown

    new_state = dict(crop_state)
    new_state["crop_start"] = crop_start
    new_state["crop_end"] = crop_end
    new_state["committed"] = is_full

    schematic_fig = build_schematic_figure(schematic, highlight_range=(crop_start, crop_end) if not is_full else None)

    return preview, badge_style, btn_style, btn_style, new_state, schematic_fig


@callback(
    Output("commit-status", "children", allow_duplicate=True),
    Output("preview-badge", "style", allow_duplicate=True),
    Output("commit-crop-btn", "style", allow_duplicate=True),
    Output("reset-crop-btn", "style", allow_duplicate=True),
    Output("current-crop-state", "data", allow_duplicate=True),
    Output("shelf-kpis", "children", allow_duplicate=True),
    Input("commit-crop-btn", "n_clicks"),
    State("shelf-selector", "value"),
    State("schematic-selector", "value"),
    State("current-crop-state", "data"),
    prevent_initial_call=True,
)
def commit_crop(n_clicks, filename, schema_key, crop_state):
    import planogram_store as ps
    hidden = {"display": "none"}
    if not n_clicks or not crop_state:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    data = gd.get_data()
    shelf = data["shelf_map"].get(filename)
    if not shelf:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    if schema_key:
        schematic = ps.get(schema_key)
    else:
        auto_key = (shelf.planogram_id, shelf.num_shelves, shelf.shelf_rank)
        schematic = data["schematics"].get(auto_key)

    if not schematic:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    crop_start = crop_state.get("crop_start", 1)
    crop_end = crop_state.get("crop_end", crop_state.get("max_cols", 30))

    cropped = _crop_schematic(schematic, crop_start, crop_end)
    cr = _compute_live(shelf, cropped)

    data["compliance_results"][filename] = cr

    new_state = dict(crop_state)
    new_state["committed"] = True

    score = cr.score
    kpis = dbc.Row([
        kpi_card("Score", f"{score * 100:.0f}%", "bullseye",
                 "success" if score >= 0.5 else ("warning" if score >= 0.3 else "danger")),
        kpi_card("Products", str(shelf.num_products), "box", "info"),
        kpi_card("Identified", f"{shelf.identified_pct:.0f}%", "eye", "success"),
        kpi_card("Out-of-Stock", str(cr.out_of_stock), "times-circle", "danger"),
    ])

    status_msg = dbc.Alert(
        [html.I(className="fas fa-check-circle me-2"),
         f"Score committed: {score * 100:.0f}% (columns {crop_start}–{crop_end})"],
        color="success", duration=4000, className="mt-2 py-2",
    )

    return status_msg, hidden, hidden, hidden, new_state, kpis


@callback(
    Output("crop-range-slider", "value", allow_duplicate=True),
    Output("commit-status", "children", allow_duplicate=True),
    Input("reset-crop-btn", "n_clicks"),
    State("current-crop-state", "data"),
    prevent_initial_call=True,
)
def reset_crop(n_clicks, crop_state):
    if not n_clicks or not crop_state:
        return dash.no_update, dash.no_update
    max_cols = crop_state.get("max_cols", 30)
    return [1, max_cols], ""


# ─── Editor Callbacks ─────────────────────────────────────────────

@callback(
    Output("editor-preview-graph", "figure"),
    Output("editor-preview-label", "children"),
    Output("editor-meta", "children"),
    Output("editor-rows-container", "children"),
    Input("editor-schematic-select", "value"),
    State("active-store-id", "data"),
)
def load_editor(schema_key, store_id):
    import planogram_store as ps
    store_id = store_id or "store-a"
    empty = go.Figure()
    if not schema_key:
        return empty, "Schematic Preview", "", html.P("Select a schematic", className="text-muted")

    if store_id == "store-a":
        sp = ps.get(schema_key)
        d = ps.get_all().get(schema_key, {})
    else:
        store_data = ps.load_store_schematics(store_id)
        d = store_data.get(schema_key, {})
        sp = ps.dict_to_schematic(d) if d else None

    if not sp:
        return empty, "Schematic Preview", "", html.P("Not found", className="text-muted")

    origin = d.get("origin", "auto")
    origin_badge = dbc.Badge("custom", color="warning") if origin == "custom" else dbc.Badge("auto-generated", color="secondary")
    meta = dbc.Row([
        kpi_card("Products", str(sp.total_products), "box", "primary"),
        kpi_card("Rows", str(len(sp.rows)), "layer-group", "info"),
        kpi_card("Source Images", str(len(sp.source_images)), "camera", "success"),
    ])

    row_editors = []
    for i, row in enumerate(sp.rows):
        row_editors.append(html.Div([
            html.Label(f"Row {i + 1} ({len(row.brands)} positions)", className="fw-bold"),
            dbc.Textarea(
                id={"type": "editor-row-input", "index": i},
                value=" | ".join(row.brands),
                style={"fontFamily": "monospace", "fontSize": "0.85rem"},
                rows=2,
            ),
            html.Div([
                html.Span(
                    b, className="badge me-1 mb-1",
                    style={"backgroundColor": gd.BRAND_COLORS.get(b, "#94a3b8"), "color": "white",
                           "fontSize": "0.65rem"},
                ) for b in row.brands
            ], className="mt-1 mb-3"),
        ]))

    row_editors.append(html.Div([
        dbc.Button([html.I(className="fas fa-plus me-1"), "Add Row"],
                   id="editor-add-row-btn", color="outline-success", size="sm"),
    ], className="mt-2"))

    fig = build_schematic_figure(sp)
    preview_label = html.Span([f"Preview: {schema_key} ", origin_badge])
    return fig, preview_label, meta, html.Div(row_editors)


@callback(
    Output("editor-status", "children"),
    Output("editor-schematic-select", "options"),
    Output("schematic-selector", "options"),
    Input("editor-save-btn", "n_clicks"),
    State("editor-schematic-select", "value"),
    State({"type": "editor-row-input", "index": dash.ALL}, "value"),
    State("active-store-id", "data"),
    prevent_initial_call=True,
)
def save_editor(n_clicks, schema_key, row_values, store_id):
    import planogram_store as ps
    store_id = store_id or "store-a"
    if not n_clicks or not schema_key:
        return dash.no_update, dash.no_update, dash.no_update

    if store_id == "store-a":
        sp = ps.get(schema_key)
    else:
        store_data = ps.load_store_schematics(store_id)
        sp = ps.dict_to_schematic(store_data[schema_key]) if schema_key in store_data else None

    if not sp:
        return dbc.Alert("Schematic not found", color="danger"), dash.no_update, dash.no_update

    new_rows = []
    for i, val in enumerate(row_values):
        brands = [b.strip() for b in val.split("|") if b.strip()]
        new_rows.append(pe.SchematicRow(row_index=i, brands=brands))

    sp.rows = new_rows
    if store_id == "store-a":
        ps.save(schema_key, sp, origin="custom")
    else:
        ps.save_for_store(store_id, schema_key, sp, origin="custom")
    gd.refresh_compliance(store_id)

    opts = _schematic_options(store_id)
    return (
        dbc.Alert(f"Saved {schema_key} ({sp.total_products} products)", color="success", duration=4000),
        opts, opts,
    )


@callback(
    Output("editor-status", "children", allow_duplicate=True),
    Output("editor-schematic-select", "options", allow_duplicate=True),
    Output("editor-schematic-select", "value", allow_duplicate=True),
    Output("schematic-selector", "options", allow_duplicate=True),
    Input("editor-reset-btn", "n_clicks"),
    State("editor-schematic-select", "value"),
    State("active-store-id", "data"),
    prevent_initial_call=True,
)
def reset_editor(n_clicks, schema_key, store_id):
    import planogram_store as ps
    store_id = store_id or "store-a"
    if not n_clicks or not schema_key:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    if store_id == "store-a":
        kt = ps._key_tuple(schema_key)
        data = gd.get_data(store_id)
        from planogram_engine import build_schematics
        auto = build_schematics(data["shelves"])
        auto_sp = auto.get(kt)
        if auto_sp:
            ps.save(schema_key, auto_sp, origin="auto")
            gd.refresh_compliance(store_id)

    opts = _schematic_options(store_id)
    return (
        dbc.Alert(f"Reset {schema_key} to auto-generated", color="info", duration=4000),
        opts, schema_key, opts,
    )


@callback(
    Output("new-schema-modal", "is_open"),
    Input("editor-new-btn", "n_clicks"),
    Input("new-schema-cancel-btn", "n_clicks"),
    Input("new-schema-create-btn", "n_clicks"),
    State("new-schema-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_new_modal(open_click, cancel_click, create_click, is_open):
    return not is_open


@callback(
    Output("editor-schematic-select", "options", allow_duplicate=True),
    Output("editor-schematic-select", "value", allow_duplicate=True),
    Output("schematic-selector", "options", allow_duplicate=True),
    Output("editor-status", "children", allow_duplicate=True),
    Input("new-schema-create-btn", "n_clicks"),
    State("new-schema-key", "value"),
    State("new-schema-rows", "value"),
    State("new-schema-cols", "value"),
    State("active-store-id", "data"),
    prevent_initial_call=True,
)
def create_new_schematic(n_clicks, key_str, num_rows, num_cols, store_id):
    import planogram_store as ps
    store_id = store_id or "store-a"
    if not n_clicks or not key_str:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    key_str = key_str.strip()
    if not key_str.startswith("P"):
        return dash.no_update, dash.no_update, dash.no_update, dbc.Alert(
            "Key must start with P (e.g. P01/3s/R1)", color="danger", duration=4000)

    try:
        kt = ps._key_tuple(key_str)
    except Exception:
        return dash.no_update, dash.no_update, dash.no_update, dbc.Alert(
            "Invalid key format. Use P01/3s/R1", color="danger", duration=4000)

    rows = [pe.SchematicRow(row_index=i, brands=["Unknown"] * int(num_cols))
            for i in range(int(num_rows))]
    sp = pe.SchematicPlanogram(
        planogram_id=kt[0], num_shelves=kt[1], shelf_rank=kt[2], rows=rows,
    )
    if store_id == "store-a":
        ps.save(key_str, sp, origin="custom")
    else:
        ps.save_for_store(store_id, key_str, sp, origin="custom")

    opts = _schematic_options(store_id)
    return opts, key_str, opts, dbc.Alert(f"Created {key_str}", color="success", duration=4000)


@callback(
    Output("editor-schematic-select", "options", allow_duplicate=True),
    Output("editor-schematic-select", "value", allow_duplicate=True),
    Output("schematic-selector", "options", allow_duplicate=True),
    Output("editor-status", "children", allow_duplicate=True),
    Input("editor-clone-btn", "n_clicks"),
    State("editor-schematic-select", "value"),
    State("active-store-id", "data"),
    prevent_initial_call=True,
)
def clone_schematic(n_clicks, schema_key, store_id):
    import planogram_store as ps
    store_id = store_id or "store-a"
    if not n_clicks or not schema_key:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    new_key = schema_key + "-copy"
    if store_id == "store-a":
        ps.clone(schema_key, new_key)
    else:
        store_data = ps.load_store_schematics(store_id)
        if schema_key in store_data:
            clone_d = dict(store_data[schema_key])
            clone_d["origin"] = "custom"
            store_data[new_key] = clone_d
            ps.save_store_schematics(store_id, store_data)

    opts = _schematic_options(store_id)
    return opts, new_key, opts, dbc.Alert(f"Cloned to {new_key}", color="info", duration=4000)


@callback(
    Output("editor-schematic-select", "options", allow_duplicate=True),
    Output("editor-schematic-select", "value", allow_duplicate=True),
    Output("schematic-selector", "options", allow_duplicate=True),
    Output("editor-status", "children", allow_duplicate=True),
    Input("editor-delete-btn", "n_clicks"),
    State("editor-schematic-select", "value"),
    State("active-store-id", "data"),
    prevent_initial_call=True,
)
def delete_schematic(n_clicks, schema_key, store_id):
    import planogram_store as ps
    store_id = store_id or "store-a"
    if not n_clicks or not schema_key:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    if store_id == "store-a":
        d = ps.get_all().get(schema_key, {})
        if d.get("origin") == "auto":
            return dash.no_update, dash.no_update, dash.no_update, dbc.Alert(
                "Cannot delete auto-generated schematics. Use Reset instead.", color="warning", duration=4000)
        ps.delete(schema_key)
    else:
        store_data = ps.load_store_schematics(store_id)
        if schema_key in store_data:
            del store_data[schema_key]
            ps.save_store_schematics(store_id, store_data)

    opts = _schematic_options(store_id)
    new_val = opts[0]["value"] if opts else None
    return opts, new_val, opts, dbc.Alert(f"Deleted {schema_key}", color="danger", duration=4000)


# ─── AI Image Upload Callbacks ─────────────────────────────────────

@callback(
    Output("ai-upload-preview", "children"),
    Output("ai-detect-btn", "disabled"),
    Output("ai-processing-status", "children"),
    Input("ai-image-upload", "contents"),
    State("ai-image-upload", "filename"),
    prevent_initial_call=True,
)
def preview_ai_upload(contents, filename):
    if not contents:
        return "", True, ""
    preview = html.Div([
        html.Img(src=contents, style={"maxWidth": "100%", "maxHeight": "200px",
                                       "borderRadius": "4px", "objectFit": "contain"}),
        html.P(filename, className="small text-muted mt-1 mb-0"),
    ])
    return preview, False, dbc.Alert(
        [html.I(className="fas fa-info-circle me-2"),
         "Image loaded. Enter a schematic key and click 'Detect Brands with AI'."],
        color="info", className="py-2 small",
    )


@callback(
    Output("ai-detect-result", "children"),
    Output("editor-schematic-select", "options", allow_duplicate=True),
    Output("editor-schematic-select", "value", allow_duplicate=True),
    Output("schematic-selector", "options", allow_duplicate=True),
    Output("ai-detect-btn", "disabled", allow_duplicate=True),
    Output("ai-processing-status", "children", allow_duplicate=True),
    Input("ai-detect-btn", "n_clicks"),
    State("ai-image-upload", "contents"),
    State("ai-image-upload", "filename"),
    State("ai-schema-key", "value"),
    State("ai-num-rows", "value"),
    State("active-store-id", "data"),
    prevent_initial_call=True,
)
def ai_detect_brands(n_clicks, contents, filename, schema_key, num_rows, store_id):
    import planogram_store as ps
    no = dash.no_update

    print(f"[AI Detect] Callback fired: n_clicks={n_clicks}, has_contents={bool(contents)}, "
          f"key={schema_key}, rows={num_rows}", flush=True)

    if not n_clicks or not contents:
        print("[AI Detect] No clicks or no contents, skipping", flush=True)
        return no, no, no, no, no, no

    if not schema_key or not schema_key.strip():
        return (
            dbc.Alert("Please enter a schematic key (e.g. P10/3s/R1)", color="warning"),
            no, no, no, False, "",
        )

    schema_key = schema_key.strip()
    if not schema_key.startswith("P"):
        return (
            dbc.Alert("Key must start with P (e.g. P10/3s/R1)", color="danger"),
            no, no, no, False, "",
        )

    try:
        kt = ps._key_tuple(schema_key)
    except Exception:
        return (
            dbc.Alert("Invalid key format. Use P01/3s/R1", color="danger"),
            no, no, no, False, "",
        )

    num_rows = int(num_rows) if num_rows else 3

    print(f"[AI Detect] Calling AI detection for {schema_key}, {num_rows} rows...", flush=True)
    brands, ai_source = _detect_brands_from_image(contents, num_rows)
    print(f"[AI Detect] Detection complete. Source: {ai_source}, "
          f"brands: {sum(len(r) for r in brands)} total", flush=True)

    rows = []
    for i, row_brands in enumerate(brands):
        rows.append(pe.SchematicRow(row_index=i, brands=row_brands))

    sp = pe.SchematicPlanogram(
        planogram_id=kt[0], num_shelves=kt[1], shelf_rank=kt[2], rows=rows,
    )

    store_id = store_id or "store-a"
    if store_id == "store-a":
        ps.save(schema_key, sp, origin="custom")
    else:
        ps.save_for_store(store_id, schema_key, sp, origin="custom")
    gd.refresh_compliance(store_id)

    opts = _schematic_options(store_id)

    source_badge = dbc.Badge(
        f"via {ai_source}", color="info" if ai_source != "fallback" else "secondary",
        className="ms-2",
    )
    brand_badges = []
    for row_idx, row_brands in enumerate(brands):
        row_items = []
        for b in row_brands:
            color = gd.BRAND_COLORS.get(b, "#94a3b8")
            row_items.append(html.Span(
                b, className="badge me-1 mb-1",
                style={"backgroundColor": color, "color": "white", "fontSize": "0.7rem"},
            ))
        brand_badges.append(html.Div([
            html.Strong(f"Row {row_idx + 1}: ", style={"fontSize": "0.8rem"}),
            *row_items,
        ], className="mb-1"))

    result_ui = html.Div([
        dbc.Alert([
            html.I(className="fas fa-check-circle me-2"),
            f"Created schematic {schema_key} with {sp.total_products} products "
            f"across {len(rows)} rows.",
            source_badge,
        ], color="success"),
        dbc.Card([
            dbc.CardHeader("Detected Brands — select schematic above to review & edit"),
            dbc.CardBody(brand_badges),
        ], className="border-0 bg-light"),
    ])

    return result_ui, opts, schema_key, opts, False, ""


def _detect_brands_from_image(contents: str, num_rows: int) -> tuple[list[list[str]], str]:
    """Call Databricks Foundation Model API to detect brands from a shelf image.

    Returns (list of brand rows, source label).
    """
    try:
        _, b64_data = contents.split(",", 1)
    except ValueError:
        b64_data = contents

    prompt = (
        f"Analyze this shelf image. Identify ALL product brands visible on the shelves, "
        f"organized into {num_rows} shelf rows from top to bottom. "
        f"For each row, list brands left to right separated by pipe (|). "
        f"Return ONLY the brand names, one row per line, using | as separator. "
        f"Example for 2 rows:\n"
        f"Marlboro | Kent | Camel | Parliament\n"
        f"Winston | Lucky Strike | Pall Mall\n"
        f"If you cannot identify a brand, use 'Unknown'."
    )

    w = _get_sdk_client()
    if w is None:
        print("[AI Detect] No SDK client available, using fallback", flush=True)
        return _fallback_brands(num_rows), "fallback"

    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_data}",
                }},
            ],
        }],
        "max_tokens": 1024,
    }

    # Strategy 1: REST API via SDK's api_client (handles auth for all auth types)
    try:
        print(f"[AI Detect] Calling FMAPI via api_client (image: {len(b64_data) // 1024}KB)", flush=True)
        resp = w.api_client.do(
            "POST",
            "/serving-endpoints/databricks-claude-haiku-4-5/invocations",
            body=payload,
        )
        print(f"[AI Detect] api_client response type: {type(resp).__name__}", flush=True)

        if isinstance(resp, dict):
            result = resp
        else:
            import json as _json
            result = _json.loads(resp) if isinstance(resp, (str, bytes)) else {}

        text = ""
        choices = result.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            text = msg.get("content", "")
        print(f"[AI Detect] Model response ({len(text)} chars): {text[:300]}", flush=True)

        if text:
            parsed = _parse_brand_response(text, num_rows)
            return parsed, "FMAPI (Claude Haiku 4.5)"

    except Exception as e:
        print(f"[AI Detect] api_client failed: {type(e).__name__}: {e}", flush=True)

    # Strategy 2: SDK serving_endpoints.query() (text-only fallback, no vision)
    try:
        print("[AI Detect] Trying SDK query() as text-only fallback...", flush=True)
        response = w.serving_endpoints.query(
            name="databricks-claude-haiku-4-5",
            messages=[{
                "role": "user",
                "content": prompt,
            }],
            max_tokens=1024,
        )

        text = ""
        if hasattr(response, "choices") and response.choices:
            msg = response.choices[0].message
            text = msg.content if hasattr(msg, "content") else str(msg)
        print(f"[AI Detect] SDK response: {text[:200]}", flush=True)

        if text:
            parsed = _parse_brand_response(text, num_rows)
            return parsed, "SDK query (text-only)"

    except Exception as e:
        print(f"[AI Detect] SDK query failed: {type(e).__name__}: {e}", flush=True)

    print("[AI Detect] All methods failed, returning fallback", flush=True)
    return _fallback_brands(num_rows), "fallback"


def _parse_brand_response(text: str, num_rows: int) -> list[list[str]]:
    """Parse the AI model response into rows of brand names."""
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    rows = []
    for line in lines:
        if "|" in line:
            brands = [b.strip() for b in line.split("|") if b.strip()]
            if brands:
                rows.append(brands)

    if not rows:
        words = [w.strip() for w in text.replace(",", "|").split("|") if w.strip()]
        if words:
            per_row = max(1, len(words) // num_rows)
            for i in range(num_rows):
                start = i * per_row
                end = start + per_row if i < num_rows - 1 else len(words)
                rows.append(words[start:end] if start < len(words) else ["Unknown"])

    while len(rows) < num_rows:
        rows.append(["Unknown"] * 5)

    if len(rows) > num_rows:
        rows = rows[:num_rows]

    return rows


def _fallback_brands(num_rows: int) -> list[list[str]]:
    """Return placeholder brands when AI detection is unavailable."""
    return [["Unknown"] * 8 for _ in range(num_rows)]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
