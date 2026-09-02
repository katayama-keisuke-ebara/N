"""PngExporter のユニットテスト。"""

from __future__ import annotations

from src.export.png_exporter import PngExporter

_SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


class TestPngExporter:
    def test_creates_file(self, tmp_path) -> None:
        output = tmp_path / "preview.png"
        PngExporter().export(_SQUARE, output)
        assert output.exists()

    def test_file_is_non_empty(self, tmp_path) -> None:
        output = tmp_path / "preview.png"
        PngExporter().export(_SQUARE, output)
        assert output.stat().st_size > 0

    def test_empty_points_does_not_raise(self, tmp_path) -> None:
        output = tmp_path / "empty.png"
        PngExporter().export([], output)
        assert output.exists()
