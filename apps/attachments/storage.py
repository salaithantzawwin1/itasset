"""Private file storage for attachments: no base URL, no public path.

Files are only ever served through the authorizing download view, which
checks the owning record's scope (design §5.2, Spec A §6.13). Overriding
`base_url` with None (instead of leaving it unset) makes Django's own
`FileSystemStorage.url()` refuse to build a link, so neither static serving
nor any template can expose the directory by accident. The location is read
from settings on every use so tests can point it at a tmp dir.
"""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """Filesystem storage rooted at PRIVATE_MEDIA_ROOT, unreachable by URL."""

    def __init__(self, **kwargs):
        kwargs.setdefault("location", None)
        super().__init__(**kwargs)

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):  # shadows FileSystemStorage's cached_property on purpose
        return None


private_storage = PrivateStorage()
