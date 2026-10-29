"""Employee-no auto-assign + New person form UX (session 44).

Covers:
- ``next_employee_no`` sequencing (series rows only, legacy keys ignored),
- the create modal pre-filling the next number and autofocusing Name,
- blank-submit assignment through the real view, and explicit values winning,
- the ``0007_renumber_employee_nos`` data migration that moves legacy rows
  (EMP1 / EMP02 / E201 / free text) onto the ``EMP-NNNN`` series without ever
  displacing a canonical row or tripping the unique constraint.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.people.models import Person, next_employee_no


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("emp-boss", "emp-boss@example.com", "x")
    client.force_login(user)
    return client


def _payload(site, **over):
    data = {
        "employee_no": "",
        "name": "New Hire",
        "email": "",
        "ldap_uid": "",
        "site": site.pk,
        "department": "",
        "is_active": "on",
    }
    data.update(over)
    return data


# ---------------------------------------------------------------- next number


def test_next_employee_no_starts_the_series(db):
    assert next_employee_no() == "EMP-0001"


def test_next_employee_no_counts_only_series_rows(db, site):
    Person.objects.create(employee_no="EMP-0003", name="In series", site=site)
    Person.objects.create(employee_no="EMP1", name="Legacy", site=site)
    Person.objects.create(employee_no="E201", name="Legacy seed", site=site)
    Person.objects.create(employee_no="__not-a-number", name="Noise", site=site)

    assert next_employee_no() == "EMP-0004"  # legacy keys never poison the run


# ------------------------------------------------------------------ create UX


def test_create_form_prefills_the_next_number_and_autofocuses_name(admin_client, db, site):
    Person.objects.create(employee_no="EMP-0002", name="Occupied", site=site)

    resp = admin_client.get(reverse("person-create"))

    assert resp.status_code == 200
    assert resp.context["form"].initial["employee_no"] == "EMP-0003"
    assert resp.context["form"]["name"].field.widget.attrs.get("autofocus") is True


def test_blank_employee_no_is_assigned_server_side(admin_client, db, site):
    resp = admin_client.post(reverse("person-create"), _payload(site))

    assert resp.status_code == 302
    assert Person.objects.get(name="New Hire").employee_no == "EMP-0001"


def test_explicit_employee_no_wins_over_auto_assign(admin_client, db, site):
    resp = admin_client.post(reverse("person-create"), _payload(site, employee_no="EMP-0777"))

    assert resp.status_code == 302
    assert Person.objects.get(name="New Hire").employee_no == "EMP-0777"


def test_assigned_number_skips_a_taken_slot(admin_client, db, site):
    Person.objects.create(employee_no="EMP-0001", name="Already there", site=site)

    admin_client.post(reverse("person-create"), _payload(site))

    assert Person.objects.get(name="New Hire").employee_no == "EMP-0002"


def test_edit_never_rewrites_the_stored_number(admin_client, db, site):
    person = Person.objects.create(employee_no="EMP-0123", name="Steady", site=site)

    get = admin_client.get(reverse("person-update", args=[person.pk]))
    assert get.context["form"].initial["employee_no"] == "EMP-0123"

    resp = admin_client.post(
        reverse("person-update", args=[person.pk]),
        _payload(site, employee_no="EMP-0123", name="Steady Renamed"),
    )
    assert resp.status_code == 302
    person.refresh_from_db()
    assert person.employee_no == "EMP-0123"
    assert person.name == "Steady Renamed"


def test_duplicate_employee_no_is_still_rejected(admin_client, db, site):
    Person.objects.create(employee_no="EMP-0042", name="Taken", site=site)

    resp = admin_client.post(reverse("person-create"), _payload(site, employee_no="EMP-0042"))

    assert resp.status_code == 200  # re-rendered with the error
    assert "employee_no" in resp.context["form"].errors


# ------------------------------------------------------------------ form layout


def test_person_form_renders_the_fine_tuned_layout(admin_client, db):
    html = admin_client.get(reverse("person-create")).content.decode()

    assert 'class="pgrid"' in html  # two-up grid instead of a long single column
    assert "autofocus" in html
    assert "Auto-assigned (EMP-0001" in html  # help text explains the number
    assert html.count('class="req"') >= 3  # required marks on No / Name / Site
    assert "pactions" in html


# ------------------------------------------------------- 0007 renumber migration


def _run_renumber():
    import importlib
    from types import SimpleNamespace

    from django.apps import apps as migration_apps
    from django.db import connection

    mig = importlib.import_module("apps.people.migrations.0007_renumber_employee_nos")
    mig.renumber_employee_nos(migration_apps, SimpleNamespace(connection=connection))


def test_renumber_moves_legacy_rows_onto_the_series_without_displacing_canonical(db, site):
    Person.objects.create(employee_no="EMP1", name="one", site=site)
    Person.objects.create(employee_no="EMP02", name="two", site=site)
    Person.objects.create(employee_no="E201", name="three", site=site)
    Person.objects.create(employee_no="abc", name="four", site=site)
    Person.objects.create(employee_no="EMP-0005", name="five", site=site)
    Person.objects.create(employee_no="EMP5", name="six", site=site)

    _run_renumber()

    values = dict(Person.objects.values_list("name", "employee_no"))
    assert values["one"] == "EMP-0001"  # trailing number kept
    assert values["two"] == "EMP-0002"
    assert values["three"] == "EMP-0201"
    assert values["five"] == "EMP-0005"  # canonical row never displaced
    assert values["four"] == "EMP-0003"  # no digits → lowest free number
    assert values["six"] == "EMP-0004"  # 5 already reserved → next free
    assert len(set(values.values())) == len(values)  # all unique


def test_renumber_is_idempotent(db, site):
    Person.objects.create(employee_no="EMP1", name="one", site=site)
    Person.objects.create(employee_no="EMP-0007", name="seven", site=site)

    _run_renumber()
    first = sorted(Person.objects.values_list("employee_no", flat=True))
    _run_renumber()
    second = sorted(Person.objects.values_list("employee_no", flat=True))

    assert first == second == ["EMP-0001", "EMP-0007"]


def test_renumber_on_empty_table_is_a_noop(db):
    _run_renumber()
    assert not Person.objects.exists()
