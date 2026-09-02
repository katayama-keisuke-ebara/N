"""FlattenPipeline の統合テスト。CadQuery 依存はすべてモック化する。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.exceptions import StepReadError
from src.pipeline import FlattenPipeline


def _make_mock_solid() -> MagicMock:
    """面積 100 mm²・法線 +Z の単一 PLANE 面を持つソリッドモックを返す。"""
    corners = [
        (0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
        (10.0, 10.0, 0.0), (0.0, 10.0, 0.0),
    ]

    def _pos_at(t: float, corner_list=corners) -> MagicMock:
        idx = int(t * len(corner_list)) % len(corner_list)
        p = MagicMock()
        p.x, p.y, p.z = corner_list[idx]
        return p

    edge = MagicMock()
    edge.positionAt.side_effect = _pos_at

    wire = MagicMock()
    wire.Edges.return_value = [edge]

    normal_vec = MagicMock()
    normal_vec.x, normal_vec.y, normal_vec.z = 0.0, 0.0, 1.0

    # LSCM/ARAP 用の tessellate モック (平坦 4 頂点メッシュ)
    mock_verts = []
    for x, y, z in corners:
        v = MagicMock(); v.x, v.y, v.z = x, y, z
        mock_verts.append(v)

    face = MagicMock()
    face.geomType.return_value = "PLANE"
    face.Area.return_value = 100.0
    face.normalAt.return_value = normal_vec
    face.outerWire.return_value = wire
    face.tessellate.return_value = (mock_verts, [(0, 1, 2), (0, 2, 3)])

    solid = MagicMock()
    solid.Faces.return_value = [face]
    return solid


@patch("src.pipeline.StepReader")
class TestFlattenPipelineRun:
    def _setup_reader(
        self, mock_cls: MagicMock, solid: MagicMock, tmp_path: Path
    ) -> Path:
        step_file = tmp_path / "part.step"
        step_file.write_text("dummy")
        mock_reader = MagicMock()
        mock_reader.get_solids.return_value = [solid]
        mock_cls.return_value = mock_reader
        return step_file

    def test_returns_expected_keys(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = self._setup_reader(mock_cls, _make_mock_solid(), tmp_path)
        result = FlattenPipeline().run(step_file, tmp_path / "out")
        required = {
            "part_area", "flattened_area", "area_diff_pct",
            "points", "holes",
            "dxf_path", "png_path", "result_path",
            "best_method", "error_rate", "quality", "neutral_radius", "warning",
        }
        assert required == set(result)

    def test_creates_dxf_file(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = self._setup_reader(mock_cls, _make_mock_solid(), tmp_path)
        result = FlattenPipeline().run(step_file, tmp_path / "out")
        assert Path(result["dxf_path"]).exists()

    def test_creates_png_file(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = self._setup_reader(mock_cls, _make_mock_solid(), tmp_path)
        result = FlattenPipeline().run(step_file, tmp_path / "out")
        assert Path(result["png_path"]).exists()

    def test_creates_result_json(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = self._setup_reader(mock_cls, _make_mock_solid(), tmp_path)
        result = FlattenPipeline().run(step_file, tmp_path / "out")
        result_path = Path(result["result_path"])
        assert result_path.exists()
        data = json.loads(result_path.read_text())
        assert "part_area" in data
        assert "flattened_area" in data
        assert "area_diff_pct" in data

    def test_output_filenames(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = self._setup_reader(mock_cls, _make_mock_solid(), tmp_path)
        out_dir = tmp_path / "out"
        FlattenPipeline().run(step_file, out_dir)
        assert (out_dir / "part_flat.dxf").exists()
        assert (out_dir / "part_preview.png").exists()
        assert (out_dir / "result.json").exists()

    def test_raises_when_no_solids(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        step_file = tmp_path / "empty.step"
        step_file.write_text("dummy")
        mock_reader = MagicMock()
        mock_reader.get_solids.return_value = []
        mock_cls.return_value = mock_reader

        with pytest.raises(StepReadError, match="ソリッド"):
            FlattenPipeline().run(step_file, tmp_path / "out")
