"""ResultWriter のユニットテスト。"""

from __future__ import annotations

import json

import pytest

from src.export.result_writer import ResultWriter


class TestResultWriter:
    def test_creates_file(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 995.0, output)
        assert output.exists()

    def test_json_keys_exist(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 995.0, output)
        data = json.loads(output.read_text())
        assert "part_area" in data
        assert "flattened_area" in data
        assert "area_diff_pct" in data

    def test_area_diff_calculation(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 950.0, output)
        data = json.loads(output.read_text())
        # |1000 - 950| / 1000 * 100 = 5.0 %
        assert abs(data["area_diff_pct"] - 5.0) < 0.001

    def test_values_are_rounded(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(1000.123456789, 999.987654321, output)
        data = json.loads(output.read_text())
        # 小数点以下 4 桁以内
        assert data["part_area"] == round(1000.123456789, 4)
        assert data["flattened_area"] == round(999.987654321, 4)

    def test_zero_part_area_no_division_error(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(0.0, 0.0, output)
        data = json.loads(output.read_text())
        assert data["area_diff_pct"] == 0.0

    def test_holes_written_to_json(self, tmp_path) -> None:
        """holes を指定すると hole_count と holes 配列が JSON に含まれる。"""
        hole = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0)]
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 995.0, output, holes=[hole])
        data = json.loads(output.read_text())
        assert data["hole_count"] == 1
        assert len(data["holes"]) == 1
        assert data["holes"][0][0] == [1.0, 1.0]

    def test_no_holes_defaults(self, tmp_path) -> None:
        """holes を渡さないとき hole_count==0, holes==[] が出力される。"""
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 995.0, output)
        data = json.loads(output.read_text())
        assert data["hole_count"] == 0
        assert data["holes"] == []

    def test_width_height_written_to_json(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 995.0, output, width=123.456, height=78.9)
        data = json.loads(output.read_text())
        assert data["width"] == 123.456
        assert data["height"] == 78.9

    def test_width_height_default_to_zero(self, tmp_path) -> None:
        output = tmp_path / "result.json"
        ResultWriter().write(1000.0, 995.0, output)
        data = json.loads(output.read_text())
        assert data["width"] == 0.0
        assert data["height"] == 0.0
