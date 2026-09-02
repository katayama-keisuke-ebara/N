"""複数部品(穴含む実形状)をNFPベースでネスティングし、上位候補を計算するサービス。"""

from __future__ import annotations

import logging

from src.exceptions import NestingError
from src.nesting.models import NestingCandidate, Part
from src.nesting.nfp_engine import NestingEngine

logger = logging.getLogger(__name__)


class NestingService:
    """複数部品(穴含む実形状)をNFPベースでネスティングし、上位候補を計算するサービス。"""

    def calculate_candidates(
        self,
        parts: list[dict],
        sheet_w: float,
        sheet_h: float,
        clearance: float,
        max_candidates: int = 3,
    ) -> list[dict]:
        """部品情報(points/holes/quantity等)から歩留まり上位 max_candidates 件の分布案を計算する。"""
        if not parts or sheet_w <= 0 or sheet_h <= 0:
            return []

        try:
            engine_parts = [
                Part(
                    id=p["id"],
                    name=p["name"],
                    outer=p["points"],
                    holes=p.get("holes") or [],
                    quantity=int(p.get("quantity", 1)),
                )
                for p in parts
                if p.get("points")
            ]
            if not engine_parts:
                return []

            engine = NestingEngine(sheet_w=sheet_w, sheet_h=sheet_h, clearance=clearance)
            candidates = engine.generate_candidates(engine_parts, max_candidates=max_candidates)

            logger.info(
                "ネスティング完了: 候補数=%d 最良歩留まり=%.2f%%",
                len(candidates),
                candidates[0].yield_pct if candidates else 0.0,
            )
            return [self._to_dict(c) for c in candidates]
        except Exception as exc:
            logger.error("ネスティング計算失敗: %s", exc)
            raise NestingError(f"ネスティング計算失敗: {exc}") from exc

    @staticmethod
    def _to_dict(candidate: NestingCandidate) -> dict:
        return {
            "strategy_name": candidate.strategy_name,
            "placements": [
                {
                    "part_id": pl.part_id,
                    "instance_no": pl.instance_no,
                    "x": pl.x,
                    "y": pl.y,
                    "rotation_deg": pl.rotation_deg,
                    "via_hole_fill": pl.via_hole_fill,
                }
                for pl in candidate.placements
            ],
            "count_per_part": candidate.count_per_part,
            "total_used_area": candidate.total_used_area,
            "total_hole_area": candidate.total_hole_area,
            "sheet_area": candidate.sheet_area,
            "remaining_area": candidate.remaining_area,
            "yield_pct": candidate.yield_pct,
        }
