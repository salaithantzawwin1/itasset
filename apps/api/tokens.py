"""Token auth for scanner clients (DEVELOPMENT.md §10/§16).

POST /api/v1/auth/token/ {username, password} → {token}.
Tokens are DRF authtoken rows; revoke = delete the row (admin action, §16).
"""

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["POST"])
@permission_classes([AllowAny])
def obtain_scanner_token(request):
    user = authenticate(
        username=request.data.get("username", ""),
        password=request.data.get("password", ""),
    )
    if user is None:
        return Response(
            {"detail": "invalid credentials", "status": status.HTTP_401_UNAUTHORIZED},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": user.username})
