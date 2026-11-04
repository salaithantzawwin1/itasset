"""Public views for the core app — currently just the branding logo.

The logo is the only user-uploaded file that must be reachable anonymously
(it is on the sign-in page), so it gets its own endpoint instead of a public
``/media/`` tree: attachments stay private and nginx needs no new alias.
"""

from django.http import FileResponse, Http404

from apps.core.models import Branding

# Browsers may cache the logo; the URL carries the upload mtime as a query
# string from the templates, so a replaced file re-fetches immediately.
LOGO_MAX_AGE = 60 * 60 * 24 * 7


def logo(request):
    row = Branding.current()
    if row is None or not row.logo:
        raise Http404("No logo uploaded")
    try:
        handle = row.logo.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Logo file missing") from exc
    response = FileResponse(handle, content_type=_content_type(row.logo.name))
    response["Cache-Control"] = f"public, max-age={LOGO_MAX_AGE}"
    return response


def _content_type(name: str) -> str:
    """Raster types only — an SVG served from this origin would run scripts."""
    suffix = name.rsplit(".", 1)[-1].lower()
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(suffix, "application/octet-stream")
