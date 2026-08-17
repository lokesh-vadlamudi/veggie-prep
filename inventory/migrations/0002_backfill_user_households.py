"""Backfill a default household for users that predate user linkage.

Runs after 0001, which already defines ``household.name`` as a plain
(non-unique) display field, so a legacy ownerless household that happens to
use the same default name cannot block the backfill. Users created after
this migration are covered by the ``post_save`` signal in
``inventory.signals``. The backfill is idempotent (``get_or_create`` on the
OneToOne ``user`` field), so it is safe to re-run.
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
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_households, migrations.RunPython.noop),
    ]
