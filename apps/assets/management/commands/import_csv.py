"""`make import FILE=x.csv` — bulk asset import (DEVELOPMENT.md §13 / §7).

Pipeline: column mapping → dry-run preview (default) → --commit.
Writes an ActivityLog entry with the file hash on commit (§13).
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.assets import services
from apps.assets.services import IMPORT_MAX_ROWS


class Command(BaseCommand):
    help = "Import assets from a CSV file (dry-run by default; pass --commit to write)."

    def add_arguments(self, parser):
        parser.add_argument("file", type=str, help="CSV file path")
        parser.add_argument(
            "--commit", action="store_true", help="actually write rows (default: dry-run preview)"
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"file not found: {path}")

        with path.open(newline="", encoding="utf-8-sig") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.DictReader(fh, dialect=dialect))

        if len(rows) > IMPORT_MAX_ROWS:
            raise CommandError(f"too many rows: {len(rows)} > {IMPORT_MAX_ROWS} (§13 cap)")

        dry_run = not options["commit"]
        result = services.import_assets_csv(rows, actor=None, dry_run=dry_run)

        mode = "DRY-RUN (no changes written)" if dry_run else "COMMITTED"
        self.stdout.write(f"\n=== CSV import — {mode} ===")
        self.stdout.write(f"file:          {path}")
        self.stdout.write(f"file sha256:   {result.file_hash}")
        self.stdout.write(f"rows:          {result.total_rows}")
        self.stdout.write(f"created:       {result.created}")
        self.stdout.write(f"duplicates:    {result.skipped_duplicates} (skipped)")
        if result.ignored_columns:
            self.stdout.write(f"ignored cols:  {', '.join(result.ignored_columns)}")
        if result.errors:
            self.stdout.write(self.style.WARNING(f"issues:        {len(result.errors)}"))
            for err in result.errors[:20]:
                self.stdout.write(self.style.WARNING(f"  row {err.row}: {err.message}"))
            if len(result.errors) > 20:
                self.stdout.write(self.style.WARNING(f"  … and {len(result.errors) - 20} more"))
        else:
            self.stdout.write(self.style.SUCCESS("issues:        none"))
        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nNothing was written. Re-run with --commit to import.")
            )
