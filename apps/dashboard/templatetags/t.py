"""{% t "key" %} template tag — session-based EN/MY UI language (ENG default).

Also exposes {% tvar "key" n=52 m=6 %} for parameterized strings.
Language: sessionKey `lang`; "en" default; falls back to "en" if key missing.
"""

from django import template

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
