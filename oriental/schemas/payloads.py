from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CollectIn(BaseModel):
    store: str = Field(..., min_length=1)
    men: int | None = Field(default=None, ge=0)
    women: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    ts: datetime

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    @field_validator("ts")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include timezone information")
        return value

    @model_validator(mode="after")
    def _calc_total(self) -> "CollectIn":
        if self.men is not None and self.women is not None and self.total is None:
            object.__setattr__(self, "total", self.men + self.women)
        return self