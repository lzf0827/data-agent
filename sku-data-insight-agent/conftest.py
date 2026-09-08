from __future__ import annotations

import os


# Unit and integration tests must never spend credits or depend on a live API.
os.environ.setdefault("AGNES_DISABLE_KEY_FILE", "true")
