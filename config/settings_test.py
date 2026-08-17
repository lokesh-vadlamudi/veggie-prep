"""Test settings: in-memory SQLite override so the suite never needs PostgreSQL.

``manage.py test`` automatically selects this module (see manage.py), so the
default database engine used by the test runner is SQLite, not PostgreSQL.
"""

import os

# Guarantee the base settings import even with no DJANGO_* variables set.
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-real-use")

from .settings import *  # noqa: F401,E402

# Fixed, non-secret test values so the suite runs identically in any
# environment (including CI with no DJANGO_* variables set).
DEBUG = False
SECRET_KEY = "test-only-secret-key-not-for-real-use"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Keep test log output quiet.
LOGGING = {"version": 1, "disable_existing_loggers": True}
