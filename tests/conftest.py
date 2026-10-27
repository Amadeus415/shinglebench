"""Isolate tests from local data: temp data dir + SQLite, mock providers only."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="shingle-test-")
os.environ["SHINGLE_DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ.setdefault("SANDBOX_BACKEND", "local")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENAI_COMPAT_API_KEY", "STRIPE_SECRET_KEY", "SEARCH_API_KEY"):
    os.environ[k] = ""
