"""Email alert sender (DEVELOPMENT.md §14 notification matrix, M4).

- Templates live in `templates/email/`, bilingual (my/en, §8).
- Idempotency (§14: "a last_sent_at row prevents duplicate emails"): the
  `EmailAlert` row is written *before* sending — a crashed send still blocks
  a duplicate (an alert that never fired is rarer than a double-bill).
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from .models import EmailAlert

log = logging.getLogger(__name__)

# §14 recipients: who gets notified for each alert kind
RECIPIENT_KINDS = {
    "warranty": ("holder", "it_lead"),
    "contract_renewal": ("it_lead", "procurement"),
    "license_over": ("it_lead",),
    # §14: daily activity digest → admins (ADMIN_EMAIL, falls back to IT lead)
    "daily_digest": ("admin",),
    # §4 scheduled report exports + §13 data-quality issues → IT lead
    "scheduled_report": ("it_lead",),
    "data_quality": ("it_lead",),
    # §14 remaining rows — these build explicit recipient lists at the call
    # site (role-in-scope + site lead rules); the mapping is the documented
    # **fallback** when nobody concrete resolves, so a configured-people gap
    # still reaches a human instead of vanishing.
    "request_pending": ("it_lead",),
    "loan_overdue": ("it_lead",),
    "damage_reported": ("it_lead",),
    "transfer_exception": ("it_lead",),
}


def resolve_recipients(kind: str, holder_email: str | None = None) -> list[str]:
    """Map §14 recipient roles → concrete addresses (env-driven, §19)."""
    recips: list[str] = []
    roles = RECIPIENT_KINDS.get(kind, ("it_lead",))
    for role in roles:
        if role == "holder" and holder_email:
            recips.append(holder_email)
        elif role == "it_lead" and settings.IT_LEAD_EMAIL:
            recips.append(settings.IT_LEAD_EMAIL)
        elif role == "procurement" and settings.PROCUREMENT_EMAIL:
            recips.append(settings.PROCUREMENT_EMAIL)
        elif role == "admin":
            # §19 env-driven: admins (digest); IT lead is the documented fallback
            addr = getattr(settings, "ADMIN_EMAIL", "") or settings.IT_LEAD_EMAIL
            if addr:
                recips.append(addr)
    # de-dup, keep order
    return list(dict.fromkeys(r for r in recips if r))


def role_emails(role: str, site=None) -> list[str]:
    """Addresses of active users who hold `role` (a Django Group) and may act
    on `site` — notification targets obey the same deny-by-default scope
    boundary a read would (design §4.3); superusers hold every role.

    `site=None` skips the scope filter (no site context exists — callers then
    usually fall back to the §14 default via `resolve_recipients`).
    v1 limitation: department-scoped users are not mapped to a site.
    """
    from django.contrib.auth import get_user_model

    from apps.core.scopes import effective_scopes

    User = get_user_model()
    candidates = (
        User.objects.filter(Q(groups__name=role) | Q(is_superuser=True), is_active=True)
        .exclude(email="")
        .distinct()
        .order_by("username")
    )
    emails: list[str] = []
    for user in candidates:
        if site is None or effective_scopes(user).allows_site(site.pk):
            emails.append(user.email)
    return list(dict.fromkeys(emails))


def send_alert(
    kind: str,
    dedupe_key: str,
    template: str,
    context: dict,
    *,
    subject: str,
    holder_email: str | None = None,
    recipients: list[str] | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Send one alert email, idempotently.

    `dedupe_key` identifies (alert kind, object, bucket) — e.g.
    "warranty:40:30" — and is unique per EmailAlert row. Returns True when
    an email actually went out this call.

    `recipients` overrides the §14 role mapping (scheduled reports address a
    concrete list, e.g. a site's lead_email); `attachments` are
    `(filename, bytes, content_type)` triples for report exports (§4).
    """
    if recipients is not None:
        recips = list(recipients)
    else:
        recips = resolve_recipients(kind, holder_email)
    recips = list(dict.fromkeys(r for r in recips if r))  # de-dup, keep order
    if not recips:
        log.info("alert skipped (no recipients): %s", dedupe_key)
        return False

    alert, created = EmailAlert.objects.get_or_create(
        dedupe_key=dedupe_key, defaults={"kind": kind, "recipients": recips}
    )
    if not created:
        return False  # already alerted — idempotent (§14/§15)

    lang = getattr(settings, "LANGUAGE_CODE", "my") or "my"
    body = render_to_string(f"email/{template}.txt", {**context, "lang": lang})
    try:
        if attachments:
            from django.core.mail import EmailMessage

            msg = EmailMessage(subject=subject, body=body, from_email=None, to=recips)
            for fname, data, mime in attachments:
                msg.attach(fname, data, mime)
            msg.send(fail_silently=False)
        else:
            send_mail(
                subject=subject,
                message=body,
                from_email=None,  # DEFAULT_FROM_EMAIL
                recipient_list=recips,
                fail_silently=False,
            )
    except Exception:
        # Sending failed — keep the row? No: delete it so the next run retries.
        alert.delete()
        log.exception("alert send failed: %s", dedupe_key)
        raise
    alert.sent_at = timezone.now()
    alert.save(update_fields=["sent_at"])
    return True
