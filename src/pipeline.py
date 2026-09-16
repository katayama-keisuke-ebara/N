from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.cad.step_reader import StepReader
from src.exceptions import (
    DxfExportError,
    PngExportError,
    ResultWriteError,
    StepReadError,
    UnfoldError,
)
from src.export.dxf_exporter import DxfExporter
from src.export.png_exporter import PngExporter
from src.export.result_writer import ResultWriter
from src.flatten.face_extractor import FaceExtractor
from src.flatten.surface_unfolder import SurfaceUnfolder

logger = logging.getLogger(__name__)


class FlattenPipeline:
    """STEP → DXF / PNG / JSON のパイプラインを統合する。"""

    def __init__(self, samples_per_edge: int = 50) -> None:
        self._extractor = FaceExtractor()
        self._unfolder = SurfaceUnfolder(samples_per_edge)
        self._dxf = DxfExporter()
        self._png = PngExporter()
        self._writer = ResultWriter()

    def run(
        self, step_path: str | Path, output_dir: str | Path
    ) -> dict:
        """パイプラインを実行し、成果物のパスと面積・品質情報を辞書で返す。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. STEP 読み込み
        try:
            reader = StepReader(step_path)
            reader.load()
            solids = reader.get_solids()
        except Exception as exc:
            logger.error("STEP 読み込み失敗: %s — %s", step_path, exc)
            raise StepReadError(f"STEP 読み込み失敗: {exc}") from exc
        if not solids:
            raise StepReadError("STEP ファイルにソリッドが存在しません")
        solid = solids[0]
        logger.info("STEP 読み込み完了: ソリッド %d 個", len(solids))

        # 2. 最大面積面を抽出
        face = self._extractor.extract_largest_face(solid)
        part_area = self._extractor.get_face_area(face)

        # 3. 展開 (曲率解析・中立面推定・MinStrain/LSCM/ARAP から最良を選択)
        try:
            best = self._unfolder.unfold(face, solid)
        except Exception as exc:
            logger.error("展開失敗: %s", exc)
            raise UnfoldError(f"展開失敗: {exc}") from exc
        flat_points = best.points
        flattened_area = best.area_flat
        logger.info(
            "展開完了: 手法=%s 誤差率=%.4f%% 品質=%s",
            best.method, best.error_rate, best.quality,
        )

        if best.warning:
            logger.warning(best.warning)
            print(best.warning, file=sys.stderr)

        holes = best.holes

        # 縦/横寸法は展開後の外周バウンディングボックスから算出
        width = max(p[0] for p in flat_points) - min(p[0] for p in flat_points) if flat_points else 0.0
        height = max(p[1] for p in flat_points) - min(p[1] for p in flat_points) if flat_points else 0.0

        # 4. DXF 出力
        dxf_path = output_dir / "part_flat.dxf"
        try:
            self._dxf.export(flat_points, dxf_path, holes=holes)
        except Exception as exc:
            logger.error("DXF 出力失敗: %s", exc)
            raise DxfExportError(f"DXF 出力失敗: {exc}") from exc
        logger.info("DXF 出力完了: %s", dxf_path)

        # 5. PNG 出力
        png_path = output_dir / "part_preview.png"
        try:
            self._png.export(flat_points, png_path, holes=holes)
        except Exception as exc:
            logger.error("PNG 出力失敗: %s", exc)
            raise PngExportError(f"PNG 出力失敗: {exc}") from exc

        # 6. result.json 出力
        result_path = output_dir / "result.json"
        try:
            self._writer.write(
                part_area, flattened_area, result_path, holes=holes, width=width, height=height
            )
        except Exception as exc:
            logger.error("result.json 出力失敗: %s", exc)
            raise ResultWriteError(f"result.json 出力失敗: {exc}") from exc

        area_diff_pct = (
            abs(part_area - flattened_area) / part_area * 100.0
            if part_area > 0.0
            else 0.0
        )

        return {
            "part_area": part_area,
            "flattened_area": flattened_area,
            "area_diff_pct": area_diff_pct,
            "points": flat_points,
            "holes": holes,
            "width": width,
            "height": height,
            "dxf_path": str(dxf_path),
            "png_path": str(png_path),
            "result_path": str(result_path),
            "best_method": best.method,
            "error_rate": best.error_rate,
            "quality": best.quality,
            "neutral_radius": best.neutral_radius,
            "warning": best.warning,
        }
