from __future__ import annotations

from pathlib import Path

import ezdxf

from src.nesting.geometry_utils import bounds, rotate_points


class DxfExporter:
    """2D ポリゴン点列を DXF R2010 形式で出力する。"""

    def export(
        self,
        points: list[tuple[float, float]],
        output_path: str | Path,
        holes: list[list[tuple[float, float]]] | None = None,
    ) -> None:
        """points を外周 LWPOLYLINE、holes を HOLES レイヤーの LWPOLYLINE として保存する。"""
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        if len(points) >= 3:
            msp.add_lwpolyline(points, close=True)
        if holes:
            doc.layers.add("HOLES", color=1)  # 赤色
            for hole in holes:
                if len(hole) >= 3:
                    msp.add_lwpolyline(hole, close=True, dxfattribs={"layer": "HOLES"})
        doc.saveas(str(output_path))

    def export_nesting(
        self,
        pipeline_results: list[dict],
        candidate: dict,
        sheet_w: float,
        sheet_h: float,
        output_path: str | Path,
    ) -> None:
        """1つのネスティング案(シート外形+全配置部品)を1つの DXF にまとめて保存する。"""
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        doc.layers.add("SHEET", color=5)  # 青色
        doc.layers.add("HOLES", color=1)  # 赤色

        sheet_corners = [(0.0, 0.0), (sheet_w, 0.0), (sheet_w, sheet_h), (0.0, sheet_h)]
        msp.add_lwpolyline(sheet_corners, close=True, dxfattribs={"layer": "SHEET"})

        # render_nesting_png と同じキー付け規則(part_id優先、無ければ stem_index)で部品を引く
        part_lookup: dict[str, dict] = {}
        for i, result in enumerate(pipeline_results):
            part_id = result.get("part_id") or f"{Path(result['step_path']).stem}_{i}"
            part_lookup[part_id] = result

        for placement in candidate.get("placements", []):
            part = part_lookup.get(placement["part_id"])
            if part is None:
                continue
            outer = rotate_points(part.get("points", []), placement["rotation_deg"])
            holes = [rotate_points(h, placement["rotation_deg"]) for h in part.get("holes", [])]
            if not outer:
                continue
            min_x, min_y, _, _ = bounds(outer)
            dx, dy = placement["x"] - min_x, placement["y"] - min_y
            outer = [(x + dx, y + dy) for x, y in outer]
            holes = [[(x + dx, y + dy) for x, y in h] for h in holes]

            if len(outer) >= 3:
                msp.add_lwpolyline(outer, close=True)
            for hole in holes:
                if len(hole) >= 3:
                    msp.add_lwpolyline(hole, close=True, dxfattribs={"layer": "HOLES"})

        doc.saveas(str(output_path))

