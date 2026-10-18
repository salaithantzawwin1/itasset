"""Person ↔ User auto-link for the employee self-view (design §4.4).

Resolution order at login (§4.4): `ldap_uid` ↔ login username, else a unique
email match. Only unambiguous, still-unlinked Person rows are adopted — the
link is a security boundary (it grants the self-view carve-out), so we never
guess and never fail a login over it.
"""

import logging

from django.contrib.auth.signals import user_logged_in

log = logging.getLogger(__name__)


def link_person(user):
    """Attach the matching Person row to *user*. Returns the Person or None.

    Never raises: a missed link only costs the self-view carve-out, while a
    broken login would cost the user their session.
    """
    from apps.people.models import Person

    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if Person.objects.filter(user=user).exists():
        return Person.objects.filter(user=user).first()

    free = Person.objects.filter(user__isnull=True, is_active=True)
    username = user.get_username()
    if username:
        match = free.filter(ldap_uid=username)
        if match.count() == 1:
            return _attach(user, match.get())

    email = (getattr(user, "email", "") or "").strip()
    if email:
        match = free.filter(email__iexact=email)
        if match.count() == 1:  # ambiguous (0 or 2+) → never guess
            return _attach(user, match.get())
    return None


def _attach(user, person):
    person.user = user
    person.save(update_fields=["user"])
    log.info("linked person %s to user %s", person.employee_no, user.get_username())
    return person


def on_login(sender, user, **kwargs):
    """user_logged_in hook: resolve the §4.4 link once per login.

    `sender`/`kwargs` are the django.contrib.auth signal's own arguments.
    """
    try:
        link_person(user)
    except Exception:  # pragma: no cover - defensive: login must never fail
        log.exception("person auto-link failed for %s", getattr(user, "username", "?"))


user_logged_in.connect(on_login, dispatch_uid="people.person_link")
