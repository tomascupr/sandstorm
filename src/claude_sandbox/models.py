import os
from posixpath import normpath

from pydantic import BaseModel, Field, field_validator, model_validator


class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1_000_000)
    anthropic_api_key: str | None = None
    e2b_api_key: str | None = None
    model: str | None = None
    max_turns: int | None = None
    timeout: int = Field(default=300, ge=5, le=3600)
    files: dict[str, str] | None = Field(
        None,
        description="Files to upload to the sandbox. Keys are relative paths under /home/user/.",
    )

    @field_validator("files")
    @classmethod
    def validate_file_paths(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        safe = {}
        for path, content in v.items():
            normalized = normpath(path).lstrip("/")
            if normalized.startswith("..") or normalized == ".":
                raise ValueError(f"Path traversal not allowed: {path}")
            safe[normalized] = content
        return safe

    @model_validator(mode="after")
    def resolve_api_keys(self):
        """Fall back to env vars if keys not provided in request body."""
        if not self.anthropic_api_key:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.e2b_api_key:
            self.e2b_api_key = os.environ.get("E2B_API_KEY")

        if not self.anthropic_api_key:
            raise ValueError(
                "anthropic_api_key is required — pass it in the request body "
                "or set ANTHROPIC_API_KEY in the environment"
            )
        if not self.e2b_api_key:
            raise ValueError(
                "e2b_api_key is required — pass it in the request body "
                "or set E2B_API_KEY in the environment"
            )
        return self
