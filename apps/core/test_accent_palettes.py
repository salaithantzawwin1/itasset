"""Guard: the six accent palettes have one source of truth.

The dashboard accent is applied to three surfaces (base.html, the sign-in page
and the admin theme). They must all include
``templates/partials/accent_palettes.css.html`` and must not define palette
values themselves — otherwise the copies drift again, which is exactly how the
admin ended up redefining ``--accent`` before the refactor.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

SHARED = "partials/accent_palettes.css.html"
SURFACES = (
    "base.html",
    "registration/login.html",
    "admin/_theme.css.html",
)
ACCENTS = ("blue", "green", "purple", "orange", "pink", "teal")

# A palette *definition* selects on the accent name; the attribute can still be
# set generically elsewhere (the head scripts do that).
DEFINITION = re.compile(r'data-accent="(?:' + "|".join(ACCENTS) + r')"')


def _templates_root():
    return Path(settings.BASE_DIR) / "templates"


def _read(relative_path):
    return (_templates_root() / relative_path).read_text(encoding="utf-8")


class AccentPaletteSourceTests(TestCase):
    def test_surfaces_include_the_shared_file_exactly_once(self):
        include_tag = f'{{% include "{SHARED}" %}}'
        for surface in SURFACES:
            text = _read(surface)
            with self.subTest(surface=surface):
                self.assertEqual(text.count(include_tag), 1)
                self.assertNotIn("data-accent=\"", text)

    def test_palette_definitions_exist_only_in_the_shared_include(self):
        offenders = []
        for path in _templates_root().rglob("*.html"):
            relative = path.relative_to(_templates_root()).as_posix()
            if relative == SHARED:
                continue
            if DEFINITION.search(path.read_text(encoding="utf-8")):
                offenders.append(relative)

        self.assertEqual(offenders, [])

    def test_shared_file_defines_every_accent_for_light_and_dark(self):
        text = _read(SHARED)

        self.assertEqual(len(DEFINITION.findall(text)), len(ACCENTS) * 2)
        for accent in ACCENTS:
            with self.subTest(accent=accent):
                self.assertEqual(text.count(f':root[data-accent="{accent}"]'), 1)
                self.assertEqual(
                    text.count(f'[data-theme="dark"][data-accent="{accent}"]'), 1
                )

    def test_every_rendered_surface_has_one_palette_block(self):
        admin = get_user_model().objects.create_superuser(
            "palette_admin", "palette@example.com", "pw12345!"
        )
        html_by_surface = {}
        # sign-in is anonymous
        self.client.logout()
        html_by_surface["login"] = self.client.get(reverse("login")).content.decode()
        # base.html via the dashboard
        self.client.force_login(admin)
        html_by_surface["dashboard"] = self.client.get("/").content.decode()
        html_by_surface["admin"] = self.client.get("/admin/").content.decode()

        for surface, html in html_by_surface.items():
            for accent in ACCENTS:
                with self.subTest(surface=surface, accent=accent):
                    self.assertEqual(html.count(f':root[data-accent="{accent}"]'), 1)
                    self.assertEqual(
                        html.count(f'[data-theme="dark"][data-accent="{accent}"]'), 1
                    )
