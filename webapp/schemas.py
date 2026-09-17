"""API リクエスト/レスポンスの pydantic スキーマ。"""

from __future__ import annotations

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
