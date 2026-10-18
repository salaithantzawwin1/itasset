"""Role helpers (DEVELOPMENT.md §11): roles are Django Groups.

Roles: admin / technician / auditor / viewer.
- Site create/update/delete: admin only.
- Asset/Person create/edit/delete: technician or admin (auditor/viewer = read).
- Reads: anything opens to any authenticated user.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


def user_has_role(user, *roles: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def is_admin(user) -> bool:
    return user_has_role(user, "admin")


def is_technician_or_admin(user) -> bool:
    return user_has_role(user, "admin", "technician")


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Subclass must set roles_required; superusers pass automatically."""

    roles_required: tuple[str, ...] = ()

    def test_func(self) -> bool:
        if not self.roles_required:
            return self.request.user.is_authenticated  # read: any logged-in user
        return user_has_role(self.request.user, *self.roles_required)
