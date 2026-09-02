"""StepReader のユニットテスト。CadQuery 依存はモック化する。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.cad.step_reader import StepReader


def test_load_raises_when_file_not_found() -> None:
    reader = StepReader("nonexistent.step")
    with pytest.raises(FileNotFoundError, match="nonexistent.step"):
        reader.load()


def test_get_solids_raises_before_load() -> None:
    reader = StepReader("test.step")
    with pytest.raises(RuntimeError):
        reader.get_solids()


@patch("src.cad.step_reader.cq.importers.importStep")
def test_load_calls_import_step(mock_import: MagicMock, tmp_path) -> None:
    step_file = tmp_path / "part.step"
    step_file.write_text("dummy content")
    mock_import.return_value = MagicMock()

    reader = StepReader(step_file)
    returned = reader.load()

    mock_import.assert_called_once_with(str(step_file))
    assert returned is reader  # メソッドチェーン確認


@patch("src.cad.step_reader.cq.importers.importStep")
def test_get_solids_returns_list(mock_import: MagicMock, tmp_path) -> None:
    step_file = tmp_path / "part.step"
    step_file.write_text("dummy content")

    mock_solid = MagicMock()
    mock_wp = MagicMock()
    mock_wp.solids.return_value.vals.return_value = [mock_solid]
    mock_import.return_value = mock_wp

    reader = StepReader(step_file)
    reader.load()
    solids = reader.get_solids()

    assert len(solids) == 1
    assert solids[0] is mock_solid
