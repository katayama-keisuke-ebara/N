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
