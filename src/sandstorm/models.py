import os
from posixpath import normpath

from pydantic import BaseModel, Field, field_validator, model_validator

PROVIDER_TOGGLE_KEYS = (
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
)


class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1_000_000)
    anthropic_api_key: str | None = None
    e2b_api_key: str | None = None
    openrouter_api_key: str | None = None
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
        if len(v) > 20:
            raise ValueError(f"Too many files: {len(v)} (max 20)")
        total_size = sum(len(content.encode()) for content in v.values())
        if total_size > 10_000_000:  # 10MB
            raise ValueError(f"Total file size {total_size:,} bytes exceeds 10MB limit")
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
        if not self.openrouter_api_key:
            self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.e2b_api_key:
            self.e2b_api_key = os.environ.get("E2B_API_KEY")

        uses_alternate_provider = any(os.environ.get(k) for k in PROVIDER_TOGGLE_KEYS)
        uses_custom_base_url = bool(os.environ.get("ANTHROPIC_BASE_URL"))
        if not self.anthropic_api_key and not uses_alternate_provider and not uses_custom_base_url:
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
