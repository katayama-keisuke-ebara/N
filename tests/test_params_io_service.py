import io

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webapp.deps import CurrentUser, get_current_user
from webapp.routers.config import router
from webapp.schemas import PartsParamsPayload
from webapp.services.params_io_service import ParamsIOService, ParamsImportError


@pytest.fixture
def params():
    return {
        "sheet_w": 1234.5, "sheet_h": 2000, "thickness": 5.5, "clearance": 0, "density": 1.234,
        "step_parts": [{"filename": "=部品.step", "quantity": -1}, {"filename": "部品.stp", "quantity": 3}],
        "manual_parts": [
            {"shape_type": "rectangle", "width": 50, "height": 100, "quantity": 2},
            {"shape_type": "circle", "circle_unit": "diameter", "circle_value": 20, "quantity": 0},
            {"shape_type": "circle", "circle_unit": "radius", "circle_value": 15, "quantity": 5},
        ],
    }


def test_round_trip(params):
    service = ParamsIOService()
    content = service.build_workbook(params)
    assert service.parse_workbook(content) == PartsParamsPayload.model_validate(params).model_dump()
    workbook = openpyxl.load_workbook(io.BytesIO(content))
    assert workbook["部品リスト"]["B3"].data_type == "s"
    workbook.close()


@pytest.mark.parametrize("mutation", ["sheet", "header", "kind", "missing", "fraction", "formula", "range", "unit"])
def test_invalid_workbook(params, mutation):
    service = ParamsIOService()
    workbook = openpyxl.load_workbook(io.BytesIO(service.build_workbook(params)))
    if mutation == "sheet":
        del workbook["設定"]
    elif mutation == "header":
        workbook["部品リスト"]["A2"] = "不明"
    elif mutation == "kind":
        workbook["部品リスト"]["A3"] = "不明"
    elif mutation == "missing":
        workbook["設定"]["B2"] = None
    elif mutation == "fraction":
        workbook["部品リスト"]["G3"] = 1.5
    elif mutation == "formula":
        workbook["設定"]["B2"] = "=100+200"
    elif mutation == "range":
        workbook["設定"]["B2"] = -1
    elif mutation == "unit":
        workbook["部品リスト"]["E6"] = "不明"
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    with pytest.raises(ParamsImportError):
        service.parse_workbook(output.getvalue())


def test_empty_parts(params):
    params.update(step_parts=[], manual_parts=[])
    service = ParamsIOService()
    assert service.parse_workbook(service.build_workbook(params)) == params


def test_not_excel():
    with pytest.raises(ParamsImportError):
        ParamsIOService().parse_workbook(b"not an Excel file")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(1, "test")
    with TestClient(app) as client:
        client.cookies.set("csrf_token", "test-csrf")
        client.headers["X-CSRF-Token"] = "test-csrf"
        yield client


def test_api_round_trip(client, params):
    response = client.post("/api/config/export", json=params)
    assert response.status_code == 200
    assert response.headers["content-type"].endswith("spreadsheetml.sheet")
    assert "netsingtool_params.xlsx" in response.headers["content-disposition"]
    restored = client.post("/api/config/import", files={"file": ("params.xlsx", response.content)})
    assert restored.status_code == 200
    assert restored.json() == PartsParamsPayload.model_validate(params).model_dump()


@pytest.mark.parametrize("filename, content", [("params.txt", b"text"), ("params.xlsx", b"invalid")])
def test_api_invalid_file(client, filename, content):
    response = client.post("/api/config/import", files={"file": (filename, content)})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_api_size_limit(client):
    response = client.post("/api/config/import", files={"file": ("params.xlsx", b"x" * (5 * 1024 * 1024 + 1))})
    assert response.status_code == 400
    assert "5 MB" in response.json()["detail"]


def test_api_invalid_export(client, params):
    params["sheet_w"] = 0
    assert client.post("/api/config/export", json=params).status_code == 422


def test_api_csrf_required(client, params):
    del client.headers["X-CSRF-Token"]
    assert client.post("/api/config/export", json=params).status_code == 403
    assert client.post("/api/config/import", files={"file": ("params.xlsx", b"")}).status_code == 403


def test_api_auth_required(client, params):
    client.app.dependency_overrides.clear()
    assert client.post("/api/config/export", json=params).status_code == 401
    assert client.post("/api/config/import", files={"file": ("params.xlsx", b"")}).status_code == 401