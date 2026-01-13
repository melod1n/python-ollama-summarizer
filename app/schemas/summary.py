from typing import Any, Literal

from pydantic import BaseModel, HttpUrl, ConfigDict


class URLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["in_progress", "success", "failure"]
    result: dict[str, Any] | None = None
    error: str | None = None
