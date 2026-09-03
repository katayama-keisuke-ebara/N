"""ネスティング配置図を PNG バイト列としてレンダリングする (GUI 非依存)。

描画ロジックは gui/nesting_view.py の NestingView.draw() と同一のアルゴリズムを維持している
(精度・見た目の同一性を保つため、座標変換や配色ロジックは変更しない)。
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

from matplotlib.figure import Figure
from matplotlib.patches import Patch, PathPatch
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.path import Path as MplPath

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [
    "Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP", "Hiragino Sans", "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False

_COLOR_CYCLE = [
    "#4da6ff", "#ff9f4d", "#7ed957", "#e05fd6", "#ffd93d", "#5fd6c8", "#d65f5f",
]


def _signed_area(points: list[tuple[float, float]]) -> float:
    n = len(points)
    return sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )


def _rotate(points: list[tuple[float, float]], angle_deg: float) -> list[tuple[float, float]]:
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return [(x * c - y * s, x * s + y * c) for x, y in points]


def _polygon_with_holes_path(
    outer: list[tuple[float, float]], holes: list[list[tuple[float, float]]]
) -> MplPath:
    verts: list[tuple[float, float]] = list(outer) + [outer[0]]
    codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(outer) - 1) + [MplPath.CLOSEPOLY]
    outer_sign = _signed_area(outer)
    for hole in holes:
        if len(hole) < 3:
            continue
        ring = list(hole)
        if _signed_area(ring) * outer_sign > 0:
            ring = ring[::-1]
        verts += ring + [ring[0]]
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 1) + [MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def render_nesting_png(
    pipeline_results: list[dict],
    candidate: dict,
    sheet_w: float,
    sheet_h: float,
) -> bytes:
    """選択中の分布案を PNG バイト列として描画する (150 DPI)。"""
    fig = Figure(figsize=(12, 4))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ax.set_facecolor("#fafafa")

    sheet_corners = [(0, 0), (sheet_w, 0), (sheet_w, sheet_h), (0, sheet_h)]
    ax.add_patch(
        MplPolygon(sheet_corners, closed=True, fill=False, edgecolor="#333333", linewidth=1.8)
    )

    part_lookup: dict[str, dict] = {}
    color_by_id: dict[str, str] = {}
    for i, result in enumerate(pipeline_results):
        # ジョブ実行時に付与された part_id (webapp/jobs.py の _safe_stem 結果) を優先し、
        # 旧データ互換のため 未付与時は単純な stem にフォールバックする。
        part_id = result.get("part_id") or f"{Path(result['step_path']).stem}_{i}"
        part_lookup[part_id] = result
        color_by_id[part_id] = _COLOR_CYCLE[i % len(_COLOR_CYCLE)]

    for placement in candidate.get("placements", []):
        part = part_lookup.get(placement["part_id"])
        if part is None:
            continue
        outer = _rotate(part.get("points", []), placement["rotation_deg"])
        holes = [_rotate(h, placement["rotation_deg"]) for h in part.get("holes", [])]
        min_x = min(p[0] for p in outer)
        min_y = min(p[1] for p in outer)
        outer = [(x - min_x + placement["x"], y - min_y + placement["y"]) for x, y in outer]
        holes = [
            [(x - min_x + placement["x"], y - min_y + placement["y"]) for x, y in h]
            for h in holes
        ]
        path = _polygon_with_holes_path(outer, holes)
        color = color_by_id[placement["part_id"]]
        ax.add_patch(
            PathPatch(path, facecolor=color, edgecolor="#1a1a1a", linewidth=0.6, alpha=0.75)
        )

    legend_handles = [
        Patch(facecolor=color_by_id[pid], edgecolor="#1a1a1a", label=part_lookup[pid]["step_path"])
        for pid in part_lookup
    ]
    legend_labels = [Path(part_lookup[pid]["step_path"]).stem for pid in part_lookup]
    if legend_handles:
        # プロット領域の下に常に配置し、定尺シートの描画と重ならないようにする
        ncol = min(len(legend_handles), 3)
        ax.legend(
            legend_handles, legend_labels, loc="upper center", bbox_to_anchor=(0.5, -0.12),
            ncol=ncol, fontsize=8, framealpha=0.8,
        )

    margin_x = sheet_w * 0.03
    margin_y = sheet_h * 0.03
    ax.set_xlim(-margin_x, sheet_w + margin_x)
    ax.set_ylim(-margin_y, sheet_h + margin_y)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    count = sum(candidate.get("count_per_part", {}).values())
    yield_pct = candidate.get("yield_pct", 0.0)
    strategy = candidate.get("strategy_name", "")
    ax.set_title(
        f"ネスティング配置図 [{strategy}]  —  取り数: {count} 個  歩留まり: {yield_pct:.1f}%"
    )
    ax.grid(True, alpha=0.25, linestyle="--")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    return buf.getvalue()
