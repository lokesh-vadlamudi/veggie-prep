"""Scaffold smoke tests.

These run under ``config.settings_test`` (in-memory SQLite) and verify the
foundation wiring: DRF is installed, settings load, and the test database
override is active.
"""

from django.test import SimpleTestCase

from config import settings_test


class ScaffoldTests(SimpleTestCase):
    def test_rest_framework_is_installed(self):
        self.assertIn("rest_framework", settings_test.INSTALLED_APPS)

    def test_test_settings_use_in_memory_sqlite(self):
        engine = settings_test.DATABASES["default"]["ENGINE"]
        self.assertEqual(engine, "django.db.backends.sqlite3")
        self.assertEqual(settings_test.DATABASES["default"]["NAME"], ":memory:")

    def test_test_settings_use_fixed_non_secret_key(self):
        # Test settings must not depend on environment-provided secrets.
        self.assertEqual(
            settings_test.SECRET_KEY, "test-only-secret-key-not-for-real-use"
        )
