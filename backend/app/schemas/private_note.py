from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00]*$")]
Body = Annotated[str, StringConstraints(max_length=50000, pattern=r"^[^\x00]*$")]


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    body: Body = ""


class NotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)
    title: Title | None = None
    body: Body | None = None

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        fields = self.model_fields_set - {"expected_version"}
        if not fields or any(getattr(self, name) is None for name in fields):
            raise ValueError("변경할 제목 또는 본문을 입력하십시오.")
        return self


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
    version_no: int
