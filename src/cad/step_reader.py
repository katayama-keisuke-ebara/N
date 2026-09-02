from __future__ import annotations

from pathlib import Path

import cadquery as cq


class StepReader:
    """STEP ファイルを読み込み、ソリッドのリストを提供する。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._workplane: cq.Workplane | None = None

    def load(self) -> "StepReader":
        """STEP ファイルを読み込む。メソッドチェーン可能。"""
        if not self._path.exists():
            raise FileNotFoundError(f"STEP file not found: {self._path}")
        self._workplane = cq.importers.importStep(str(self._path))
        return self

    def get_solids(self) -> list[cq.Shape]:
        """読み込んだファイルからソリッドのリストを返す。"""
        if self._workplane is None:
            raise RuntimeError("load() を先に呼び出してください")
        return self._workplane.solids().vals()
