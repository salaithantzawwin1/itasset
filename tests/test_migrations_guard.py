"""Deploy guard (gap §3.7 / step 8): a model edit without its generated
migration must fail here, not surprise the production `migrate`."""

from io import StringIO

import pytest
from django.core.management import call_command

# makemigrations introspects the DB (content types / applied state)
pytestmark = pytest.mark.django_db


def test_no_model_change_without_a_migration():
    """`makemigrations --check` in test form.

    pytest-django runs every migration when building the test database, so a
    *missing* migration file is otherwise invisible until the server deploy.
    """
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out)
    except SystemExit:
        pytest.fail(f"model changes without migrations:\n{out.getvalue()}")
