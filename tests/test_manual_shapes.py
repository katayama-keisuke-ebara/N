from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from webapp.jobs import _build_manual_result, _run_job
from webapp.routers.jobs import create_job
from webapp.schemas import CreateJobRequest, ManualShapeInput
from webapp.services.nesting_service import NestingService


def test_manual_shape_schema_validates_dimensions() -> None:
    rectangle = ManualShapeInput(shape_type="rectangle", width=100, height=40, quantity=3)
    circle = ManualShapeInput(shape_type="circle", radius=25, quantity=2)

    assert rectangle.width == 100
    assert circle.radius == 25
    with pytest.raises(ValidationError):
        ManualShapeInput(shape_type="rectangle", width=100)
    with pytest.raises(ValidationError):
        ManualShapeInput(shape_type="circle")


def test_create_job_request_allows_manual_parts_without_uploads() -> None:
    request = CreateJobRequest(
        parts=[],
        manual_parts=[{"shape_type": "circle", "radius": 20, "quantity": 1}],
        sheet_w=500,
        sheet_h=500,
        thickness=10,
        clearance=5,
        density=1,
    )

    assert request.parts == []
    assert len(request.manual_parts) == 1


def test_manual_results_feed_existing_nesting_service() -> None:
    rectangle = _build_manual_result(
        {"shape_type": "rectangle", "width": 100, "height": 40, "quantity": 2}, 0
    )
    circle = _build_manual_result(
        {"shape_type": "circle", "radius": 20, "quantity": 1}, 1
    )
    parts = [
        {
            "id": result["part_id"],
            "name": result["display_name"],
            "points": result["points"],
            "holes": result["holes"],
            "quantity": result["quantity"],
        }
        for result in (rectangle, circle)
    ]

    candidates = NestingService().calculate_candidates(
        parts, sheet_w=500, sheet_h=500, clearance=5
    )

    assert candidates
    assert candidates[0]["count_per_part"][rectangle["part_id"]] == 2
    assert candidates[0]["count_per_part"][circle["part_id"]] == 1


def test_manual_only_job_generates_nesting_outputs(tmp_path) -> None:
    class ProgressQueue:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def put(self, message: tuple[str, str]) -> None:
            self.messages.append(message)

    progress_queue = ProgressQueue()
    outcome = _run_job(
        "manual-job",
        [],
        [
            {"shape_type": "rectangle", "width": 100, "height": 40, "quantity": 2},
            {"shape_type": "circle", "radius": 20, "quantity": 1},
        ],
        500,
        500,
        10,
        5,
        1,
        str(tmp_path),
        progress_queue,
    )

    assert len(outcome["results"]) == 2
    assert all(result["source_type"] == "manual" for result in outcome["results"])
    assert outcome["candidates"]
    assert list(tmp_path.glob("nesting_*.dxf"))
    assert (tmp_path / "summary.xlsx").is_file()
    assert progress_queue.messages[-1] == ("manual-job", "完了")


def test_create_job_accepts_manual_parts_only(monkeypatch) -> None:
    captured: dict = {}

    def fake_create_job(job_id: str, user_id: int, params: dict) -> None:
        captured["job_id"] = job_id
        captured["user_id"] = user_id
        captured["params"] = params

    class DummyJobManager:
        def submit(
            self,
            job_id,
            resolved_parts,
            manual_parts,
            sheet_w,
            sheet_h,
            thickness,
            clearance,
            density,
            output_dir,
        ):
            captured["submit"] = {
                "job_id": job_id,
                "resolved_parts": resolved_parts,
                "manual_parts": manual_parts,
                "sheet_w": sheet_w,
                "sheet_h": sheet_h,
                "thickness": thickness,
                "clearance": clearance,
                "density": density,
                "output_dir": output_dir,
            }

    monkeypatch.setattr("webapp.routers.jobs.db.create_job", fake_create_job)
    monkeypatch.setattr(
        "webapp.routers.jobs.storage.job_output_dir",
        lambda user_id, job_id: Path("dummy-output"),
    )

    body = CreateJobRequest(
        parts=[],
        manual_parts=[{"shape_type": "rectangle", "width": 120, "height": 80, "quantity": 5}],
        sheet_w=1000,
        sheet_h=2000,
        thickness=10,
        clearance=5,
        density=1,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(job_manager=DummyJobManager())))
    user = SimpleNamespace(id=1, username="tester")

    result = create_job(body=body, request=request, user=user)

    assert "job_id" in result
    assert captured["user_id"] == 1
    assert captured["submit"]["resolved_parts"] == []
    assert captured["submit"]["manual_parts"][0]["shape_type"] == "rectangle"
    assert captured["submit"]["manual_parts"][0]["quantity"] == 5