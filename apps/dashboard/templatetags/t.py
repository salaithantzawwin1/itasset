"""{% t "key" %} template tag — session-based EN/MY UI language (ENG default).

Also exposes {% tvar "key" n=52 m=6 %} for parameterized strings.
Language: sessionKey `lang`; "en" default; falls back to "en" if key missing.
"""

import html
import re

from django import template
from django.utils.safestring import mark_safe

from apps.dashboard.i18n import STRINGS

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key, **params):
    request = context.get("request")
    lang = "en"
    if request is not None:
        lang = getattr(request, "session", {}).get("lang", "en") or "en"
    entry = STRINGS.get(key) or {}
    text = entry.get(lang) or entry.get("en") or key
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return text


@register.simple_tag
def highlight(value, query):
    """{% highlight value q %} — wrap case-insensitive matches of `query`
    inside `value` in <mark>, so search results show WHY a row matched.

    Match and non-match alike stay HTML-escaped; <mark> is the only markup
    added, so a value or a query carrying HTML can never inject. Blank
    query → plain escaped text (unchanged rendering for non-search pages).
    """
    text = "" if value is None else str(value)
    needle = "" if query is None else str(query).strip()
    if not needle:
        return mark_safe(html.escape(text))
    # re.split with one capture group keeps the matches at the odd indices
    parts = re.split(f"({re.escape(needle)})", text, flags=re.IGNORECASE)
    return mark_safe(
        "".join(
            f"<mark>{html.escape(part)}</mark>" if i % 2 else html.escape(part)
            for i, part in enumerate(parts)
        )
    )
