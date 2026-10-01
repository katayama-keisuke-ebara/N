"""業務機能の統合テスト。

対象:
  - ConfigService: 設定保存・復元
  - ExportService: summary.xlsx 生成・行追記
  - setup_logging: ログファイル生成
  - FlattenPipeline: StepReadError / UnfoldError / DxfExportError の送出
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from webapp.services.config_service import ConfigService
from webapp.services.export_service import ExportService
from webapp.schemas import PartInput
from src.exceptions import DxfExportError, StepReadError, UnfoldError
from src.log_setup import setup_logging


# ──────────────────────────────────────────────
# ConfigService
# ──────────────────────────────────────────────

class TestConfigService:
    def test_load_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        cfg = ConfigService(tmp_path / "config.json").load()
        assert cfg["sheet_w"] == 1000.0
        assert cfg["sheet_h"] == 2000.0
        assert cfg["parts"] == []

    def test_save_creates_file(self, tmp_path: Path) -> None:
        svc = ConfigService(tmp_path / "config.json")
        svc.save({"parts": [{"path": "a.step", "quantity": 1}], "sheet_w": 500.0,
                  "sheet_h": 1000.0, "thickness": 5.0, "clearance": 3.0})
        assert (tmp_path / "config.json").exists()

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        svc = ConfigService(tmp_path / "config.json")
        original = {"parts": [{"path": "part.step", "quantity": 2}], "sheet_w": 800.0,
                    "sheet_h": 1200.0, "thickness": 8.0, "clearance": 4.0}
        svc.save(original)
        restored = svc.load()
        assert restored == original

    def test_load_migrates_legacy_step_path(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"step_path": "old.step", "sheet_w": 700.0}), encoding="utf-8")
        cfg = ConfigService(p).load()
        assert cfg["parts"] == [{"path": "old.step", "quantity": 1}]
        assert cfg["sheet_w"] == 700.0

    def test_load_ignores_unknown_keys(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"sheet_w": 600.0, "unknown_key": "x"}), encoding="utf-8")
        cfg = ConfigService(p).load()
        assert "unknown_key" not in cfg
        assert cfg["sheet_w"] == 600.0

    def test_load_handles_corrupt_file(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text("NOT JSON", encoding="utf-8")
        cfg = ConfigService(p).load()
        assert cfg["sheet_w"] == 1000.0  # デフォルト値にフォールバック


# ──────────────────────────────────────────────
# PartInput — quantity <= 0 は自動計算モードのセンチネル値
# ──────────────────────────────────────────────

class TestPartInputSchema:
    @pytest.mark.parametrize("quantity", [0, -1, -5])
    def test_non_positive_quantity_is_accepted_as_auto_sentinel(self, quantity: int) -> None:
        part = PartInput(upload_id="u1", quantity=quantity)
        assert part.quantity == quantity

    def test_quantity_above_upper_bound_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            PartInput(upload_id="u1", quantity=10001)


# ──────────────────────────────────────────────
# ExportService — summary.xlsx
# ──────────────────────────────────────────────

def _make_results() -> list[dict]:
    return [{
        "step_path": "tests/step/part.step",
        "quantity": 1,
        "part_area": 1000.0,
        "flattened_area": 995.0,
        "area_diff_pct": 0.5,
        "quality": "A",
        "best_method": "lscm",
        "holes": [],
    }]


def _make_candidate() -> dict:
    return {
        "strategy_name": "area_desc",
        "count_per_part": {"part_0": 6},
        "yield_pct": 75.0,
        "remaining_area": 50000.0,
        "total_hole_area": 0.0,
        "total_used_area": 5970.0,  # 995.0 (flattened_area) * 6
        "sheet_area": 2000000.0,  # sheet_w * sheet_h
    }


def _make_params() -> dict:
    return {
        "parts": [{"path": "tests/step/part.step", "quantity": 1}],
        "sheet_w": 1000.0,
        "sheet_h": 2000.0,
        "thickness": 10.0,
        "clearance": 5.0,
        "density": 1.0,
    }


class TestExportServiceSummary:
    def test_creates_summary_file(self, tmp_path: Path) -> None:
        ExportService().append_to_summary(
            _make_results(), _make_candidate(), _make_params(), tmp_path
        )
        assert (tmp_path / "summary.xlsx").exists()

    def test_summary_sheet_name(self, tmp_path: Path) -> None:
        ExportService().append_to_summary(
            _make_results(), _make_candidate(), _make_params(), tmp_path
        )
        wb = openpyxl.load_workbook(tmp_path / "summary.xlsx")
        assert "Summary" in wb.sheetnames

    def test_summary_has_header_row(self, tmp_path: Path) -> None:
        ExportService().append_to_summary(
            _make_results(), _make_candidate(), _make_params(), tmp_path
        )
        wb = openpyxl.load_workbook(tmp_path / "summary.xlsx")
        ws = wb["Summary"]
        assert ws.cell(row=1, column=1).value == "処理日時"

    def test_summary_appends_rows(self, tmp_path: Path) -> None:
        svc = ExportService()
        svc.append_to_summary(_make_results(), _make_candidate(), _make_params(), tmp_path)
        svc.append_to_summary(_make_results(), _make_candidate(), _make_params(), tmp_path)
        wb = openpyxl.load_workbook(tmp_path / "summary.xlsx")
        ws = wb["Summary"]
        # ヘッダー行 + データ 2 行
        assert ws.max_row == 3

    def test_summary_sheet_size_column(self, tmp_path: Path) -> None:
        ExportService().append_to_summary(
            _make_results(), _make_candidate(), _make_params(), tmp_path
        )
        wb = openpyxl.load_workbook(tmp_path / "summary.xlsx")
        ws = wb["Summary"]
        # 定尺列は 8 列目
        assert "×" in str(ws.cell(row=2, column=8).value)

    def test_summary_weight_columns(self, tmp_path: Path) -> None:
        ExportService().append_to_summary(
            _make_results(), _make_candidate(), _make_params(), tmp_path
        )
        wb = openpyxl.load_workbook(tmp_path / "summary.xlsx")
        ws = wb["Summary"]
        assert ws.cell(row=1, column=9).value == "密度 (g/cm³)"
        assert ws.cell(row=1, column=10).value == "部材重量合計 (kg)"
        assert ws.cell(row=1, column=11).value == "端材重量 (kg)"
        # total_used_area(5970.0) * thickness(10.0) * density(1.0) / 1e6
        assert ws.cell(row=2, column=10).value == pytest.approx(0.0597)
        # scrap_area = sheet_area(2000000.0) - total_used_area(5970.0) - total_hole_area(0.0)
        assert ws.cell(row=2, column=11).value == pytest.approx(19.9403)

    def test_save_excel_sheet_name_is_summary(self, tmp_path: Path) -> None:
        dst = str(tmp_path / "out.xlsx")
        ExportService().save_excel(
            _make_results(), _make_candidate(), _make_params(), dst
        )
        wb = openpyxl.load_workbook(dst)
        assert "Summary" in wb.sheetnames

    @pytest.mark.parametrize(("weight_kg", "expected"), [
        (0.23, "0.23kg (230g)"),
        (0.0597, "0.0597kg (60g)"),
        (0.0005, "0.0005kg (1g)"),
        (0.00049, "0.0005kg (0g)"),
        (0.0, "0.0kg (0g)"),
    ])
    def test_save_excel_weight_units(
        self, tmp_path: Path, weight_kg: float, expected: str,
    ) -> None:
        results = _make_results()
        candidate = _make_candidate()
        params = _make_params()
        params["thickness"] = 1.0
        results[0]["flattened_area"] = weight_kg * 1_000_000 / 2
        candidate["count_per_part"] = {"part_0": 2}
        candidate["total_used_area"] = weight_kg * 1_000_000
        candidate["total_hole_area"] = 100.0
        candidate["sheet_area"] = candidate["total_used_area"] * 2 + 100.0
        dst = tmp_path / "weights.xlsx"

        ExportService().save_excel(results, candidate, params, str(dst))

        wb = openpyxl.load_workbook(dst)
        summary = {row[0]: row[1:] for row in wb["Summary"].iter_rows(values_only=True)}
        assert summary["部材重量合計"] == (expected, None)
        assert summary["端材重量"] == (expected, None)
        assert wb["Parts"].cell(row=1, column=7).value == "重量"
        assert wb["Parts"].cell(row=2, column=7).value == expected
        wb.close()


# ──────────────────────────────────────────────
# setup_logging
# ──────────────────────────────────────────────

class TestLogging:
    def test_creates_log_file(self, tmp_path: Path) -> None:
        import logging
        # ルートロガーをリセットして独立させる
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        root.handlers.clear()
        try:
            setup_logging(log_dir=tmp_path)
            assert (tmp_path / "app.log").exists()
        finally:
            for h in root.handlers:
                h.close()
            root.handlers.clear()
            root.handlers.extend(original_handlers)

    def test_no_double_init(self, tmp_path: Path) -> None:
        import logging
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        root.handlers.clear()
        try:
            setup_logging(log_dir=tmp_path)
            count_after_first = len(root.handlers)
            setup_logging(log_dir=tmp_path)  # 2 回目は何もしない
            assert len(root.handlers) == count_after_first
        finally:
            for h in root.handlers:
                h.close()
            root.handlers.clear()
            root.handlers.extend(original_handlers)


# ──────────────────────────────────────────────
# Pipeline error handling
# ──────────────────────────────────────────────

@patch("src.pipeline.StepReader")
class TestPipelineErrors:
    def test_step_read_error_on_missing_file(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_cls.return_value.load.side_effect = FileNotFoundError("not found")
        from src.pipeline import FlattenPipeline
        with pytest.raises(StepReadError):
            FlattenPipeline().run(tmp_path / "missing.step", tmp_path)

    def test_step_read_error_on_no_solids(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = tmp_path / "empty.step"
        step_file.write_text("dummy")
        mock_reader = MagicMock()
        mock_reader.get_solids.return_value = []
        mock_cls.return_value = mock_reader
        from src.pipeline import FlattenPipeline
        with pytest.raises(StepReadError, match="ソリッド"):
            FlattenPipeline().run(step_file, tmp_path)

    def test_unfold_error_propagates(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = tmp_path / "part.step"
        step_file.write_text("dummy")
        mock_reader = MagicMock()
        mock_reader.get_solids.return_value = [MagicMock()]
        mock_cls.return_value = mock_reader
        from src.pipeline import FlattenPipeline
        pipeline = FlattenPipeline()
        pipeline._extractor = MagicMock()
        pipeline._unfolder = MagicMock()
        pipeline._unfolder.unfold.side_effect = RuntimeError("unfold boom")
        with pytest.raises(UnfoldError):
            pipeline.run(step_file, tmp_path)

    def test_dxf_export_error_propagates(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = tmp_path / "part.step"
        step_file.write_text("dummy")
        mock_solid = MagicMock()
        mock_reader = MagicMock()
        mock_reader.get_solids.return_value = [mock_solid]
        mock_cls.return_value = mock_reader

        from src.flatten.models import UnfoldResult
        mock_result = UnfoldResult(
            method="lscm",
            points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
            area_3d=100.0,
            area_flat=98.0,
            error_rate=2.0,
            quality="A",
        )
        from src.pipeline import FlattenPipeline
        pipeline = FlattenPipeline()
        pipeline._extractor = MagicMock()
        pipeline._extractor.get_face_area.return_value = 100.0
        pipeline._unfolder = MagicMock()
        pipeline._unfolder.unfold.return_value = mock_result
        pipeline._dxf = MagicMock()
        pipeline._dxf.export.side_effect = OSError("disk full")
        with pytest.raises(DxfExportError):
            pipeline.run(step_file, tmp_path)
