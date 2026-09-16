"""DxfExporter のユニットテスト。"""

from __future__ import annotations

import ezdxf
import pytest

from src.export.dxf_exporter import DxfExporter

_SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


class TestDxfExporter:
    def test_creates_file(self, tmp_path) -> None:
        output = tmp_path / "out.dxf"
        DxfExporter().export(_SQUARE, output)
        assert output.exists()

    def test_file_is_valid_dxf(self, tmp_path) -> None:
        output = tmp_path / "out.dxf"
        DxfExporter().export(_SQUARE, output)
        doc = ezdxf.readfile(str(output))
        assert doc is not None

    def test_contains_lwpolyline(self, tmp_path) -> None:
        output = tmp_path / "out.dxf"
        DxfExporter().export(_SQUARE, output)
        doc = ezdxf.readfile(str(output))
        entities = list(doc.modelspace())
        assert len(entities) == 1
        assert entities[0].dxftype() == "LWPOLYLINE"

    def test_polyline_is_closed(self, tmp_path) -> None:
        output = tmp_path / "out.dxf"
        DxfExporter().export(_SQUARE, output)
        doc = ezdxf.readfile(str(output))
        poly = list(doc.modelspace())[0]
        assert poly.closed is True

    def test_single_point_no_entity(self, tmp_path) -> None:
        """点が 1 つ以下のとき LWPOLYLINE を生成しない。"""
        output = tmp_path / "out.dxf"
        DxfExporter().export([(0.0, 0.0)], output)
        doc = ezdxf.readfile(str(output))
        assert len(list(doc.modelspace())) == 0

    def test_empty_points_no_entity(self, tmp_path) -> None:
        output = tmp_path / "out.dxf"
        DxfExporter().export([], output)
        doc = ezdxf.readfile(str(output))
        assert len(list(doc.modelspace())) == 0

    def test_holes_written_to_holes_layer(self, tmp_path) -> None:
        """holes に指定した輪郭が HOLES レイヤーに出力される。"""
        hole = [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]
        output = tmp_path / "holes.dxf"
        DxfExporter().export(_SQUARE, output, holes=[hole])
        doc = ezdxf.readfile(str(output))
        entities = list(doc.modelspace())
        assert len(entities) == 2
        layers = {e.dxf.layer for e in entities}
        assert "HOLES" in layers

    def test_empty_holes_no_extra_entity(self, tmp_path) -> None:
        output = tmp_path / "noholes.dxf"
        DxfExporter().export(_SQUARE, output, holes=[])
        doc = ezdxf.readfile(str(output))
        assert len(list(doc.modelspace())) == 1


class TestExportNesting:
    def _candidate(self, placements: list[dict]) -> dict:
        return {"placements": placements}

    def test_creates_file_with_sheet_boundary(self, tmp_path) -> None:
        output = tmp_path / "nesting.dxf"
        DxfExporter().export_nesting([], self._candidate([]), 100.0, 200.0, output)
        doc = ezdxf.readfile(str(output))
        entities = list(doc.modelspace())
        assert len(entities) == 1
        assert entities[0].dxf.layer == "SHEET"
        assert entities[0].closed is True

    def test_places_part_translated_by_xy(self, tmp_path) -> None:
        results = [{"step_path": "a.step", "part_id": "p0", "points": _SQUARE, "holes": []}]
        candidate = self._candidate(
            [{"part_id": "p0", "x": 10.0, "y": 20.0, "rotation_deg": 0.0}]
        )
        output = tmp_path / "placed.dxf"
        DxfExporter().export_nesting(results, candidate, 100.0, 200.0, output)
        doc = ezdxf.readfile(str(output))
        entities = [e for e in doc.modelspace() if e.dxf.layer != "SHEET"]
        assert len(entities) == 1
        points = [(p[0], p[1]) for p in entities[0].get_points()]
        assert (10.0, 20.0) in points
        assert (20.0, 30.0) in points

    def test_places_part_with_rotation_and_holes(self, tmp_path) -> None:
        hole = [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]
        results = [{"step_path": "a.step", "part_id": "p0", "points": _SQUARE, "holes": [hole]}]
        candidate = self._candidate(
            [{"part_id": "p0", "x": 0.0, "y": 0.0, "rotation_deg": 90.0}]
        )
        output = tmp_path / "rotated.dxf"
        DxfExporter().export_nesting(results, candidate, 100.0, 200.0, output)
        doc = ezdxf.readfile(str(output))
        entities = list(doc.modelspace())
        # SHEET(1) + outer(1) + hole(1)
        assert len(entities) == 3
        layers = {e.dxf.layer for e in entities}
        assert {"SHEET", "HOLES"} <= layers

    def test_unknown_part_id_is_skipped(self, tmp_path) -> None:
        candidate = self._candidate(
            [{"part_id": "missing", "x": 0.0, "y": 0.0, "rotation_deg": 0.0}]
        )
        output = tmp_path / "skip.dxf"
        DxfExporter().export_nesting([], candidate, 100.0, 200.0, output)
        doc = ezdxf.readfile(str(output))
        entities = [e for e in doc.modelspace() if e.dxf.layer != "SHEET"]
        assert len(entities) == 0

