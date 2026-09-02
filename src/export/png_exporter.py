from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # ヘッドレス環境向け（GUI ウィンドウを開かない）
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon


class PngExporter:
    """2D ポリゴンを matplotlib で描画し PNG ファイルとして出力する。"""

    def export(
        self,
        points: list[tuple[float, float]],
        output_path: str | Path,
        holes: list[list[tuple[float, float]]] | None = None,
    ) -> None:
        """points を境ポリゴン、holes を白抜きポリゴンとして 150 DPI の PNG に保存する。"""
        fig, ax = plt.subplots(figsize=(8, 8))

        if points:
            xs = [p[0] for p in points] + [points[0][0]]
            ys = [p[1] for p in points] + [points[0][1]]
            ax.plot(xs, ys, color="steelblue", linewidth=1.2)
            poly = MplPolygon(
                points,
                closed=True,
                alpha=0.3,
                facecolor="cyan",
                edgecolor="steelblue",
            )
            ax.add_patch(poly)

        if holes:
            for hole in holes:
                if len(hole) < 2:
                    continue
                # 白抜きで境ポリゴンを上書きし、輪郭を赤線で表示
                ax.add_patch(MplPolygon(
                    hole, closed=True, facecolor="white", edgecolor="red",
                    linewidth=1.0, linestyle="--", alpha=1.0,
                ))

        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_title("Flat Projection Preview")
        plt.tight_layout()
        try:
            plt.savefig(str(output_path), dpi=150)
        finally:
            plt.close(fig)
