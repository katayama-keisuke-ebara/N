from __future__ import annotations

from pathlib import Path

import ezdxf


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
