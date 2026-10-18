"""DRF permissions (DEVELOPMENT.md §11): role groups map to API abilities.

- reads: any authenticated user (session or token)
- lifecycle mutations (check-out/in/receive): technician or admin
- token auth is for scanner clients (§16); session auth for the web app
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.roles import user_has_role


class IsAuthenticatedAny(BasePermission):
    """Any authenticated user (session OR token)."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsTechnicianOrAdmin(BasePermission):
    """technician+ may mutate lifecycle state; reads stay open (SAFE_METHODS)."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return user_has_role(request.user, "admin", "technician")


class IsAdmin(BasePermission):
    """admin role only (e.g. destructive endpoints)."""

    def has_permission(self, request, view):
        return user_has_role(request.user, "admin")
