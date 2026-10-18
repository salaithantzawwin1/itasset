"""CSV import tests (M2 completion; DEVELOPMENT.md §13).

Covers: column mapping, dry-run (nothing written), commit writes rows +
ActivityLog with file hash, duplicate tag/serial skip, normalisation
(serial uppercased), max-5000-row cap, unknown category/site errors.
"""

import pytest

from apps.assets import services
from apps.assets.models import Asset

pytestmark = pytest.mark.django_db

CSV = """\
asset_tag,category,site,serial_no,model,status,condition,warranty_end,extra_col
IT-HW-LAP-9001,IT-HW-LAP,yangon,sn-9001x,ThinkPad T14,IN_STOCK,GOOD,2027-01-01,ignored
IT-HW-LAP-9002,IT-HW-LAP,yangon,SN-9002X,ThinkPad X1,Available,Good,2027-06-01,ignored
"""


@pytest.fixture
def seeded(db, site, category):
    return site, category


def test_dry_run_writes_nothing(seeded):
    result = services.import_assets_csv(CSV, dry_run=True)
    assert result.dry_run is True
    assert result.created == 2
    assert result.errors == []
    assert "extra_col" in result.ignored_columns
    assert Asset.objects.count() == 0  # nothing written


def test_commit_creates_rows_and_logs_file_hash(seeded, django_user_model):
    actor = django_user_model.objects.create_user("imp", "i@x.com", "pass12345!")
    result = services.import_assets_csv(CSV, actor=actor, dry_run=False)
    assert result.created == 2
    assert Asset.objects.count() == 2

    from apps.audit.models import ActivityLog

    entry = ActivityLog.objects.filter(action="csv_import").first()
    assert entry is not None
    assert entry.actor == actor
    assert entry.details["file_hash"] == result.file_hash
    assert entry.details["created"] == 2


def test_serial_normalised_uppercase(seeded):
    services.import_assets_csv(CSV, dry_run=False)
    assert Asset.objects.get(asset_tag="IT-HW-LAP-9001").serial_no == "SN-9001X"


def test_duplicate_tag_skipped(seeded):
    csv2 = CSV + "IT-HW-LAP-9001,IT-HW-LAP,yangon,SN-OTHER,Other,IN_STOCK,GOOD,\n"
    result = services.import_assets_csv(csv2, dry_run=False)
    assert result.created == 2
    assert result.skipped_duplicates == 1
    assert any("duplicate asset_tag" in e.message for e in result.errors)


def test_duplicate_serial_same_model_skipped(seeded):
    csv2 = CSV + "IT-HW-LAP-9003,IT-HW-LAP,yangon,sn-9001x,ThinkPad T14,IN_STOCK,GOOD,\n"
    result = services.import_assets_csv(csv2, dry_run=False)
    assert result.skipped_duplicates == 1
    assert any("duplicate serial_no" in e.message for e in result.errors)


def test_unknown_category_is_row_error(seeded):
    header = "asset_tag,category,site,serial_no,model,status,condition\n"
    bad = header + "IT-HW-XXX-1,NOPE,yangon,SN-1,M,IN_STOCK,GOOD\n"
    result = services.import_assets_csv(bad, dry_run=False)
    assert result.created == 0
    assert any("unknown category" in e.message for e in result.errors)


def test_max_rows_cap(seeded):
    rows = "asset_tag,category,site\n" + "".join(
        f"TAG-{i},IT-HW-LAP,yangon\n" for i in range(services.IMPORT_MAX_ROWS + 1)
    )
    result = services.import_assets_csv(rows, dry_run=True)
    assert result.created == 0
    assert any("too many rows" in e.message for e in result.errors)
