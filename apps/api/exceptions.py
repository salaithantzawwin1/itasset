"""Consistent error envelope for DRF-raised errors (Spec A §10.9, gap §3.5).

`detail` stays exactly where clients and the existing tests expect it; `code`
(the exception's machine-readable code) and `correlationId` (minted/echoed by
`CorrelationMiddleware`) are added so a screenshot of an error is enough to
find the matching server log. Field-level validation errors (dicts of lists)
are left untouched — clients iterate those by field name.
"""

from rest_framework.views import exception_handler

# DRF exceptions carry `default_code`; Django's Http404/PermissionDenied are
# converted to DRF equivalents inside the handler, so map the status instead.
_STATUS_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    429: "throttled",
}


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" in response.data:
        request = context.get("request")
        code = getattr(exc, "default_code", None) or _STATUS_CODES.get(
            response.status_code, "error"
        )
        response.data.setdefault("code", code)
        response.data.setdefault("correlationId", getattr(request, "correlation_id", "") or "")
    return response
