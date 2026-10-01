"""API リクエスト/レスポンスの pydantic スキーマ。"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class PartInput(BaseModel):
    upload_id: str
    # 0以下は「定尺から最大何個切り出せるか自動計算する」センチネル値として扱う。
    quantity: int = Field(default=1, le=10000)


class ManualShapeInput(BaseModel):
    shape_type: Literal["rectangle", "circle"]
    width: float | None = Field(default=None, gt=0, le=100000)
    height: float | None = Field(default=None, gt=0, le=100000)
    radius: float | None = Field(default=None, gt=0, le=50000)
    quantity: int = Field(default=1, le=10000)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "ManualShapeInput":
        if self.shape_type == "rectangle" and (self.width is None or self.height is None):
            raise ValueError("矩形には幅と高さが必要です")
        if self.shape_type == "circle" and self.radius is None:
            raise ValueError("円形には半径が必要です")
        return self


class CreateJobRequest(BaseModel):
    parts: list[PartInput]
    manual_parts: list[ManualShapeInput] = Field(default_factory=list)
    sheet_w: float = Field(gt=0, le=100000)
    sheet_h: float = Field(gt=0, le=100000)
    thickness: float = Field(gt=0, le=1000)
    clearance: float = Field(ge=0, le=1000)
    density: float = Field(gt=0, le=50)


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    error: str | None = None


class UserConfigRequest(BaseModel):
    parts: list[dict] = Field(default_factory=list)
    sheet_w: float = 1000.0
    sheet_h: float = 2000.0
    thickness: float = 10.0
    clearance: float = 5.0
    density: float = 1.0


class StepPartItem(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=1, le=10000)

    @model_validator(mode="after")
    def validate_filename(self) -> "StepPartItem":
        if not self.filename.lower().endswith((".step", ".stp")) or any(
            char in self.filename for char in ("/", "\\", "\x00")
        ):
            raise ValueError("STEP のファイル名を指定してください")
        return self


class ManualShapeItem(BaseModel):
    shape_type: Literal["rectangle", "circle"]
    width: float | None = Field(default=None, gt=0, le=100000)
    height: float | None = Field(default=None, gt=0, le=100000)
    circle_unit: Literal["diameter", "radius"] = "diameter"
    circle_value: float | None = Field(default=None, gt=0, le=100000)
    quantity: int = Field(default=1, le=10000)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "ManualShapeItem":
        radius = None
        if self.shape_type == "circle" and self.circle_value is not None:
            radius = self.circle_value / 2 if self.circle_unit == "diameter" else self.circle_value
        ManualShapeInput(
            shape_type=self.shape_type, width=self.width, height=self.height,
            radius=radius, quantity=self.quantity,
        )
        return self


class PartsParamsPayload(BaseModel):
    sheet_w: float = Field(gt=0, le=100000)
    sheet_h: float = Field(gt=0, le=100000)
    thickness: float = Field(gt=0, le=1000)
    clearance: float = Field(ge=0, le=1000)
    density: float = Field(gt=0, le=50)
    step_parts: list[StepPartItem] = Field(default_factory=list, max_length=10000)
    manual_parts: list[ManualShapeItem] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def validate_numbers(self) -> "PartsParamsPayload":
        if not all(math.isfinite(getattr(self, key)) for key in (
            "sheet_w", "sheet_h", "thickness", "clearance", "density",
        )):
            raise ValueError("設定値には有限の数値を指定してください")
        return self
