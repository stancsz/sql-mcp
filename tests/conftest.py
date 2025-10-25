"""
Pytest conftest to ensure the project package is importable during tests.

This adds the repository root to sys.path so test modules can import the
local `sql_mcp_server` package without needing an editable install.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
