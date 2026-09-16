from __future__ import annotations

import json
from pathlib import Path


class ResultWriter:
    """面積計算結果を result.json として出力する。"""

    def write(
        self,
        part_area: float,
        flattened_area: float,
        output_path: str | Path,
        holes: list[list[tuple[float, float]]] | None = None,
        width: float = 0.0,
        height: float = 0.0,
    ) -> None:
        """part_area・flattened_area・面積差分率 (%)・穴情報・縦横寸法を JSON 形式で保存する。"""
        if part_area > 0.0:
            diff_pct = abs(part_area - flattened_area) / part_area * 100.0
        else:
            diff_pct = 0.0

        hole_list = holes or []
        result = {
            "part_area": round(part_area, 4),
            "flattened_area": round(flattened_area, 4),
            "area_diff_pct": round(diff_pct, 4),
            "width": round(width, 4),
            "height": round(height, 4),
            "hole_count": len(hole_list),
            "holes": [[list(pt) for pt in hole] for hole in hole_list],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
