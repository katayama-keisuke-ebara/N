from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font

logger = logging.getLogger(__name__)

_SUMMARY_HEADERS = [
    "処理日時", "部品一覧", "分布案", "取り数合計", "歩留まり (%)",
    "残材面積 (mm²)", "穴面積合計 (mm²)", "定尺",
    "密度 (g/cm³)", "部材重量合計 (kg)", "端材重量 (kg)",
]

_PARTS_HEADERS = [
    "部品名", "数量指定", "配置数", "部品面積 (3D, mm²)", "展開面積 (mm²)", "穴面積合計 (mm²)",
    "重量 (kg)",
]


def _weight_kg(area_mm2: float, thickness_mm: float, density_g_cm3: float) -> float:
    """mm² × mm × g/cm³ を kg に換算する (mm³をcm³化してgを得てからkgへ)。"""
    return area_mm2 * thickness_mm * density_g_cm3 / 1_000_000.0


def _scrap_area(candidate: dict) -> float:
    """シート面積から配置部品の正味面積と穴面積を差し引いた端材面積。"""
    return max(
        0.0,
        candidate.get("sheet_area", 0) - candidate.get("total_used_area", 0)
        - candidate.get("total_hole_area", 0),
    )


class ExportService:
    """DXF コピーと Excel 出力を担当するサービス。"""

    def save_dxf(self, src_path: str, dst_path: str) -> None:
        """既存 DXF をユーザー指定のパスへコピーする。"""
        shutil.copy2(src_path, dst_path)
        logger.info("DXF を保存しました: %s", dst_path)

    def save_excel(
        self,
        results: list[dict],
        candidate: dict,
        params: dict,
        dst_path: str,
    ) -> None:
        """計算結果と加工パラメータを Excel ファイル (.xlsx) に書き出す。"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"

        sheet_size = f"{params.get('sheet_w', 0):.0f}×{params.get('sheet_h', 0):.0f} mm"
        sheet_area = params.get("sheet_w", 0) * params.get("sheet_h", 0)
        count_per_part = candidate.get("count_per_part", {})

        header_font = Font(bold=True)
        left = Alignment(horizontal="left")

        rows: list[tuple] = [
            ("項目", "値", "単位"),
            ("処理日時", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""),
            ("部品数", len(results), "種類"),
            ("定尺", sheet_size, ""),
            ("分布案", candidate.get("strategy_name", ""), ""),
            ("取り数合計", sum(count_per_part.values()), "個"),
            ("歩留まり", round(candidate.get("yield_pct", 0), 2), "%"),
            ("残材面積", round(candidate.get("remaining_area", 0), 4), "mm²"),
            ("穴面積合計", round(candidate.get("total_hole_area", 0), 4), "mm²"),
            ("材料厚み", params.get("thickness", 0), "mm"),
            ("クリアランス", params.get("clearance", 0), "mm"),
            ("定尺面積", round(sheet_area, 4), "mm²"),
            ("密度", params.get("density", 0), "g/cm³"),
            (
                "部材重量合計",
                round(_weight_kg(
                    candidate.get("total_used_area", 0), params.get("thickness", 0),
                    params.get("density", 0),
                ), 4),
                "kg",
            ),
            (
                "端材重量",
                round(_weight_kg(
                    _scrap_area(candidate), params.get("thickness", 0), params.get("density", 0),
                ), 4),
                "kg",
            ),
        ]

        for row_idx, row_data in enumerate(rows, start=1):
            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.alignment = left
                if row_idx == 1:
                    cell.font = header_font
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 24

        parts_ws = wb.create_sheet("Parts")
        for col_idx, header in enumerate(_PARTS_HEADERS, start=1):
            cell = parts_ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for row_idx, result in enumerate(results, start=2):
            part_id = result.get("part_id") or f"{Path(result['step_path']).stem}_{row_idx - 2}"
            quantity = result.get("quantity", 1)
            quantity_label = "自動(最大)" if quantity <= 0 else quantity
            count = count_per_part.get(part_id, 0)
            parts_ws.append([
                Path(result["step_path"]).stem,
                quantity_label,
                count,
                round(result.get("part_area", 0), 4),
                round(result.get("flattened_area", 0), 4),
                round(sum(_hole_area(h) for h in result.get("holes", [])), 4),
                round(_weight_kg(
                    result.get("flattened_area", 0) * count, params.get("thickness", 0),
                    params.get("density", 0),
                ), 4),
            ])
        for col in parts_ws.columns:
            parts_ws.column_dimensions[col[0].column_letter].width = 22

        wb.save(dst_path)
        logger.info("Excel を保存しました: %s", dst_path)

    def append_to_summary(
        self,
        results: list[dict],
        candidate: dict,
        params: dict,
        output_dir: str | Path = "output",
    ) -> None:
        """実行結果を summary.xlsx の Summary シートに 1 行追記する。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "summary.xlsx"

        sheet_size = f"{params.get('sheet_w', 0):.0f}×{params.get('sheet_h', 0):.0f} mm"
        part_names = ", ".join(Path(r["step_path"]).stem for r in results)
        count_per_part = candidate.get("count_per_part", {})
        new_row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            part_names,
            candidate.get("strategy_name", ""),
            sum(count_per_part.values()),
            round(candidate.get("yield_pct", 0), 2),
            round(candidate.get("remaining_area", 0), 4),
            round(candidate.get("total_hole_area", 0), 4),
            sheet_size,
            params.get("density", 0),
            round(_weight_kg(
                candidate.get("total_used_area", 0), params.get("thickness", 0),
                params.get("density", 0),
            ), 4),
            round(_weight_kg(
                _scrap_area(candidate), params.get("thickness", 0), params.get("density", 0),
            ), 4),
        ]

        if summary_path.exists():
            wb = openpyxl.load_workbook(summary_path)
            ws = wb["Summary"] if "Summary" in wb.sheetnames else wb.active
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Summary"
            # ヘッダー行
            header_font = Font(bold=True)
            for col_idx, header in enumerate(_SUMMARY_HEADERS, start=1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 22

        ws.append(new_row)
        wb.save(summary_path)
        logger.info("summary.xlsx に行を追記しました: %s", summary_path)


def _hole_area(points: list[tuple[float, float]]) -> float:
    """穴ポリゴンの靴紐公式面積 (絶対値) を返す。"""
    n = len(points)
    if n < 3:
        return 0.0
    s = sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )
    return abs(s) / 2.0
