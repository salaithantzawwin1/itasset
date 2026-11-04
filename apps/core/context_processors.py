"""Template context shared by every page.

Only ``branding`` lives here: the sign-in page and the top bar both need the
company name/logo, and both render outside any view that could pass it.
"""

from apps.core.models import Branding

DEFAULT_BRAND_NAME = "IT Asset Manager"


def branding(request):
    """Expose the active Branding row (or None → templates use defaults).

    ``brand_name`` is the concatenation-free form used in <title> blocks and
    the top bar: the operator's company name when set, else the product name.
    """
    try:
        row = Branding.current()
    except Exception:  # pragma: no cover - pre-migration / DB outage
        row = None
    return {
        "branding": row,
        "brand_name": (row.company_name if row else DEFAULT_BRAND_NAME),
    }
