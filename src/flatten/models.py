from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CurvatureInfo:
    gaussian_mean: float        # |K| 平均 (mm⁻²)
    gaussian_max: float         # |K| 最大 (mm⁻²)
    mean_curvature_abs: float   # |H| 平均 (mm⁻¹)
    is_developable: bool        # |K|_max < 1e-4 → 展開可能面
    surface_type: str           # "PLANE" | "CYLINDER" | "GENERAL"


@dataclass
class UnfoldResult:
    method: str                           # "min_strain" | "lscm" | "arap"
    points: list[tuple[float, float]]     # 外周 2D 点列
    area_3d: float                        # face.Area() (mm²)
    area_flat: float                      # 展開後面積 (mm²)
    error_rate: float                     # % — 展開誤差率
    quality: str                          # "A" | "B" | "C"
    holes: list[list[tuple[float, float]]] = field(default_factory=list)  # 穴輪郭 2D 点列
    neutral_radius: float | None = None
    warning: str | None = None
