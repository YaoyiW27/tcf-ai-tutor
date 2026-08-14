"""Test setup for the backend.

Set a dummy DATABASE_URL before any ``app.*`` import: pydantic-settings requires
it, but no test touches Postgres (all DB/LLM access is mocked).
"""

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
