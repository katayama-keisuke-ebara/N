"""FaceExtractor のユニットテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.flatten.face_extractor import FaceExtractor


def _make_face(area: float, geom_type: str = "PLANE") -> MagicMock:
    face = MagicMock()
    face.Area.return_value = area
    face.geomType.return_value = geom_type
    return face


class TestExtractLargestFace:
    def test_returns_face_with_max_area(self) -> None:
        extractor = FaceExtractor()
        f1, f2, f3 = _make_face(10.0), _make_face(50.0), _make_face(20.0)
        solid = MagicMock()
        solid.Faces.return_value = [f1, f2, f3]

        result = extractor.extract_largest_face(solid)

        assert result is f2

    def test_selects_cylinder_when_it_is_largest(self) -> None:
        """曲面が最大面積なら曲面を選択する（仕様: 面種別を問わず最大面積）。"""
        extractor = FaceExtractor()
        cyl = _make_face(9999.0, "CYLINDER")
        plane = _make_face(1000.0, "PLANE")
        solid = MagicMock()
        solid.Faces.return_value = [cyl, plane]

        result = extractor.extract_largest_face(solid)

        assert result is cyl

    def test_raises_when_no_faces(self) -> None:
        extractor = FaceExtractor()
        solid = MagicMock()
        solid.Faces.return_value = []

        with pytest.raises(ValueError):
            extractor.extract_largest_face(solid)

    def test_single_face(self) -> None:
        extractor = FaceExtractor()
        face = _make_face(100.0)
        solid = MagicMock()
        solid.Faces.return_value = [face]

        assert extractor.extract_largest_face(solid) is face


class TestGetFaceArea:
    def test_returns_area_value(self) -> None:
        extractor = FaceExtractor()
        face = _make_face(42.5)
        assert extractor.get_face_area(face) == 42.5


class TestGetFaceNormal:
    def test_returns_normal_tuple(self) -> None:
        extractor = FaceExtractor()
        face = MagicMock()
        normal_vec = MagicMock()
        normal_vec.x, normal_vec.y, normal_vec.z = 0.0, 0.0, 1.0
        face.normalAt.return_value = normal_vec

        result = extractor.get_face_normal(face)

        assert result == (0.0, 0.0, 1.0)
