"""Stage B review report (ITAM_Scope_RBAC_Design_v1.0 §5.4).

Shadow mode keeps the UI unchanged but records every access that WOULD have
been denied once enforcement flips on (`scope_shadow_deny` ActivityLog rows).
This command aggregates those events so an operator can decide when it is safe
to set SCOPE_ENFORCEMENT_ENABLED=1.
"""

from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import ActivityLog
from apps.core.scopes import SHADOW_ACTION


class Command(BaseCommand):
    help = "Review Stage B shadow 'would-deny' scope events (design §5.4)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--since", type=int, default=7, metavar="DAYS", help="Look-back window (default 7)"
        )
        parser.add_argument(
            "--recent", type=int, default=20, metavar="N", help="Events to list (default 20)"
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["since"])
        events = list(
            ActivityLog.objects.filter(action=SHADOW_ACTION, created_at__gte=cutoff)
            .select_related("actor")
            .order_by("-created_at")
        )
        if not events:
            self.stdout.write(f"no {SHADOW_ACTION} events in the last {options['since']} day(s).")
            self.stdout.write(
                "review looks clean — after confirming every user has scopes, enforcement"
                " can be enabled (SCOPE_ENFORCEMENT_ENABLED=1)."
            )
            return

        by_user: dict[str, list] = defaultdict(list)
        for e in events:
            by_user[e.actor.username if e.actor else "anonymous"].append(e)

        self.stdout.write(f"{SHADOW_ACTION} events since {cutoff:%Y-%m-%d} ({len(events)} total)")
        self.stdout.write(f"{'user':<24} {'events':>6}  first → last")
        for name in sorted(by_user, key=lambda n: -len(by_user[n])):
            rows = by_user[name]
            span = f"{rows[-1].created_at:%Y-%m-%d %H:%M} → {rows[0].created_at:%Y-%m-%d %H:%M}"
            self.stdout.write(f"{name:<24} {len(rows):>6}  {span}")

        self.stdout.write("")
        self.stdout.write(f"most recent {min(options['recent'], len(events))} event(s):")
        for e in events[: options["recent"]]:
            who = e.actor.username if e.actor else "anonymous"
            det = e.details or {}
            hide = det.get("would_hide")
            extra = f" would_hide={hide}" if hide is not None else ""
            line = (
                f"  {e.created_at:%Y-%m-%d %H:%M:%S}  {who:<18} "
                f"{det.get('scope_action', '?'):<22} {det.get('path', '')}{extra}  "
                f"{e.object_repr}"
            )
            self.stdout.write(line)

        self.stdout.write("")
        self.stdout.write(
            "review: grant the missing scopes (admin → user access scopes, or"
            " scope_backfill_report --apply for admin roles), then flip"
            " SCOPE_ENFORCEMENT_ENABLED=1 once legitimate access stops appearing here."
        )
