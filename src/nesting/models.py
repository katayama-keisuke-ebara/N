"""ネスティングエンジンのデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass
class Part:
    """ネスティング対象の1部品種別（穴を含む展開済み2D形状）。"""

    id: str
    name: str
    outer: list[Point]
    holes: list[list[Point]] = field(default_factory=list)
    quantity: int = 1
    net_area: float = 0.0


@dataclass
class PlacedInstance:
    """シート上に配置された部品1個分の変換情報。"""

    part_id: str
    instance_no: int
    x: float
    y: float
    rotation_deg: float
    via_hole_fill: bool = False  # Tier2(穴埋めヒューリスティック)経由の配置か


@dataclass
class NestingCandidate:
    """1つの分布案（戦略）の配置結果。"""

    strategy_name: str
    placements: list[PlacedInstance]
    count_per_part: dict[str, int]
    total_used_area: float
    total_hole_area: float
    sheet_area: float
    remaining_area: float
    yield_pct: float
