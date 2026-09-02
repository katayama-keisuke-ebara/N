from __future__ import annotations

import logging

import cadquery as cq
import numpy as np

from .models import CurvatureInfo

logger = logging.getLogger(__name__)


class CurvatureAnalyzer:
    """面の曲率を解析し展開可能性を判定する。"""

    _DEVELOPABLE_THRESHOLD = 1e-4  # |K|_max がこの値未満なら展開可能

    def analyze(self, face: cq.Face, n_samples: int = 10) -> CurvatureInfo:
        """面をサンプリングし CurvatureInfo を返す。OCC 呼び出し失敗時は安全な既定値を返す。"""
        try:
            return self._analyze_impl(face, n_samples)
        except Exception as exc:
            logger.warning("曲率解析に失敗したため GENERAL/展開可能として扱います: %s", exc)
            return CurvatureInfo(0.0, 0.0, 0.0, True, "GENERAL")

    # ------------------------------------------------------------------ #

    def _analyze_impl(self, face: cq.Face, n_samples: int) -> CurvatureInfo:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
        from OCP.GeomLProp import GeomLProp_SLProps
        from OCP.BRep import BRep_Tool

        adaptor = BRepAdaptor_Surface(face.wrapped)
        surf_type = adaptor.GetType()

        if surf_type == GeomAbs_Plane:
            return CurvatureInfo(0.0, 0.0, 0.0, True, "PLANE")

        if surf_type == GeomAbs_Cylinder:
            r = adaptor.Cylinder().Radius()
            return CurvatureInfo(0.0, 0.0, 1.0 / (2.0 * r), True, "CYLINDER")

        # 一般曲面: u-v グリッドでサンプリング
        u0, u1 = adaptor.FirstUParameter(), adaptor.LastUParameter()
        v0, v1 = adaptor.FirstVParameter(), adaptor.LastVParameter()
        surf = BRep_Tool.Surface_s(face.wrapped)
        props = GeomLProp_SLProps(surf, 2, 1e-6)

        ks, hs = [], []
        for i in range(n_samples):
            for j in range(n_samples):
                u = u0 + (u1 - u0) * i / max(n_samples - 1, 1)
                v = v0 + (v1 - v0) * j / max(n_samples - 1, 1)
                props.SetParameters(u, v)
                if props.IsCurvatureDefined():
                    ks.append(props.GaussianCurvature())
                    hs.append(abs(props.MeanCurvature()))

        if not ks:
            return CurvatureInfo(0.0, 0.0, 0.0, True, "GENERAL")

        k_abs = np.abs(ks)
        k_mean = float(np.mean(k_abs))
        k_max = float(np.max(k_abs))
        h_mean = float(np.mean(hs))
        return CurvatureInfo(
            k_mean, k_max, h_mean, k_max < self._DEVELOPABLE_THRESHOLD, "GENERAL"
        )
