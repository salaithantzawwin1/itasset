"""Stage A backfill report (ITAM_Scope_RBAC_Design_v1.0 §5.4 Stage A).

Default run is a read-only report: every user with their roles, existing
scope count, and the suggested action. `--apply` writes GLOBAL scopes for
admin-role users who have no scope rows at all (idempotent — re-running
creates nothing). All other unscoped users are listed for manual
assignment: there is no data source to infer which sites a technician
covers, so the report asks a human (design §2, D-backfill).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.core.models import UserAccessScope

BACKFILL_REASON = "Stage A backfill — admin role (RBAC design §5.4)"


class Command(BaseCommand):
    help = "Report (or with --apply, create) Stage A scope backfill: admin-role users → GLOBAL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Create GLOBAL scopes for admin-role users who have no scopes yet",
        )
        parser.add_argument(
            "--actor",
            metavar="USERNAME",
            help="User recorded as created_by (default: first superuser)",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        apply_changes = options["apply"]

        eligible_ids = set(
            User.objects.filter(groups__name="admin").values_list("id", flat=True)
        ) | set(User.objects.filter(is_superuser=True).values_list("id", flat=True))
        scope_counts = dict(
            UserAccessScope.objects.values("user_id")
            .annotate(n=Count("id"))
            .values_list("user_id", "n")
        )

        backfill = []  # admin-role users with zero scope rows
        review = []  # everyone else with zero scope rows
        self.stdout.write(f"{'username':<24} {'roles':<26} {'scopes':>6}  action")
        for u in User.objects.order_by("username").prefetch_related("groups"):
            roles = ",".join(sorted(g.name for g in u.groups.all()))
            if u.is_superuser:
                roles = f"{roles},superuser" if roles else "superuser"
            n_scopes = scope_counts.get(u.id, 0)
            if n_scopes:
                action = "ok (has scope)"
            elif u.id in eligible_ids:
                backfill.append(u)
                action = "BACKFILL → GLOBAL (pending)" if apply_changes else "BACKFILL → GLOBAL"
            else:
                review.append(u)
                action = "REVIEW (no scope)"
            self.stdout.write(f"{u.username:<24} {roles or '-':<26} {n_scopes:>6}  {action}")

        if apply_changes and backfill:
            actor = self._resolve_actor(User, options["actor"])
            for u in backfill:
                UserAccessScope.objects.create(
                    user=u,
                    scope_type=UserAccessScope.ScopeType.GLOBAL,
                    reason=BACKFILL_REASON,
                    created_by=actor,
                )
            names = ", ".join(u.username for u in backfill)
            self.stdout.write(
                self.style.SUCCESS(
                    f"created {len(backfill)} GLOBAL scope(s) as {actor.username!r}: {names}"
                )
            )
        elif apply_changes:
            self.stdout.write("nothing to apply — every admin-role user already has a scope")

        self.stdout.write("")
        self.stdout.write(
            f"summary: {len(backfill)} backfill candidate(s), "
            f"{len(review)} user(s) need manual scope assignment (Stage A report)"
        )
        if review:
            self.stdout.write(
                self.style.WARNING(
                    "unscoped users (assign sites/departments via the admin scope UI): "
                    + ", ".join(u.username for u in review)
                )
            )

    def _resolve_actor(self, User, username):
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"--actor user {username!r} not found") from None
        actor = User.objects.filter(is_superuser=True).order_by("id").first()
        if actor is None:
            raise CommandError("no superuser exists to record as created_by; pass --actor USERNAME")
        return actor
