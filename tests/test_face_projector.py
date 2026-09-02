"""FaceProjector のユニットテスト。純 Python ロジックのみ検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from src.flatten.face_projector import FaceProjector


class TestComputeRotationMatrix:
    def test_identity_when_normal_is_z(self) -> None:
        proj = FaceProjector()
        R = proj.compute_rotation_matrix((0.0, 0.0, 1.0))
        assert np.allclose(R, np.eye(3))

    def test_negative_z_normal(self) -> None:
        proj = FaceProjector()
        R = proj.compute_rotation_matrix((0.0, 0.0, -1.0))
        # R @ n = +z
        n = np.array([0.0, 0.0, -1.0])
        assert np.allclose(R @ n, [0.0, 0.0, 1.0], atol=1e-9)

    def test_x_axis_normal(self) -> None:
        proj = FaceProjector()
        R = proj.compute_rotation_matrix((1.0, 0.0, 0.0))
        n = np.array([1.0, 0.0, 0.0])
        assert np.allclose(R @ n, [0.0, 0.0, 1.0], atol=1e-9)

    def test_y_axis_normal(self) -> None:
        proj = FaceProjector()
        R = proj.compute_rotation_matrix((0.0, 1.0, 0.0))
        n = np.array([0.0, 1.0, 0.0])
        assert np.allclose(R @ n, [0.0, 0.0, 1.0], atol=1e-9)

    def test_diagonal_normal(self) -> None:
        proj = FaceProjector()
        n_raw = (1.0, 1.0, 1.0)
        R = proj.compute_rotation_matrix(n_raw)
        n = np.array(n_raw) / np.linalg.norm(n_raw)
        assert np.allclose(R @ n, [0.0, 0.0, 1.0], atol=1e-9)

    def test_output_is_rotation_matrix(self) -> None:
        """R^T R = I かつ det(R) = +1 を確認する。"""
        proj = FaceProjector()
        R = proj.compute_rotation_matrix((0.3, 0.7, 0.6))
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-9)
        assert abs(np.linalg.det(R) - 1.0) < 1e-9


class TestGetPolygonArea:
    def test_square_10x10(self) -> None:
        proj = FaceProjector()
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert abs(proj.get_polygon_area(pts) - 100.0) < 1e-9

    def test_right_triangle(self) -> None:
        proj = FaceProjector()
        pts = [(0.0, 0.0), (4.0, 0.0), (0.0, 3.0)]
        assert abs(proj.get_polygon_area(pts) - 6.0) < 1e-9

    def test_clockwise_same_result(self) -> None:
        """靴紐公式は絶対値を返すため巻き順に依存しない。"""
        proj = FaceProjector()
        ccw = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        cw = list(reversed(ccw))
        assert abs(proj.get_polygon_area(ccw) - proj.get_polygon_area(cw)) < 1e-9

    def test_empty_returns_zero(self) -> None:
        proj = FaceProjector()
        assert proj.get_polygon_area([]) == 0.0

    def test_one_point_returns_zero(self) -> None:
        proj = FaceProjector()
        assert proj.get_polygon_area([(1.0, 2.0)]) == 0.0

    def test_two_points_returns_zero(self) -> None:
        proj = FaceProjector()
        assert proj.get_polygon_area([(0.0, 0.0), (1.0, 1.0)]) == 0.0
