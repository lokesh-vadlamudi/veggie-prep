"""Backfill a default household for users that predate user linkage.

Users created after this migration are covered by the ``post_save`` signal in
``inventory.signals``; this data migration covers pre-existing users. It is
idempotent (``get_or_create``), so it is safe to re-run.
"""

from django.db import migrations


def backfill_households(apps, schema_editor):
    User = apps.get_model("auth", "user")
    Household = apps.get_model("inventory", "household")
    for user in User.objects.all():
        Household.objects.get_or_create(
            user_id=user.pk,
            defaults={"name": f"{user.username}'s household"},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_household_user_stocklot_location"),
    ]

    operations = [
        migrations.RunPython(backfill_households, migrations.RunPython.noop),
    ]
