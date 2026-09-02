from __future__ import annotations

import cadquery as cq


class FaceExtractor:
    """ソリッドから最大面積の面を抽出する。"""

    def extract_largest_face(self, solid: cq.Shape) -> cq.Face:
        """ソリッドの全面を走査し、面積が最大の面を返す。"""
        faces = solid.Faces()
        if not faces:
            raise ValueError("ソリッドに面が存在しません")
        return max(faces, key=lambda f: f.Area())

    def get_face_area(self, face: cq.Face) -> float:
        """面の面積 (mm²) を返す。"""
        return face.Area()

    def get_face_normal(self, face: cq.Face) -> tuple[float, float, float]:
        """面中心における法線ベクトルを返す。"""
        n = face.normalAt()
        return (n.x, n.y, n.z)
