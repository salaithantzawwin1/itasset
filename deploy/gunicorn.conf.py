"""Gunicorn config for the IT Asset Manager (DEVELOPMENT.md §24).

Server binds 127.0.0.1:8001; nginx (port 80/LAN) proxies to it.
"""

import multiprocessing

bind = "127.0.0.1:8001"
workers = max(2, multiprocessing.cpu_count() * 2 + 1)
# Import the app once in the master, then fork: every worker starts warm.
# Without this, the first request each worker serves pays the full import
# cost. Measured on the live dashboard: 0.36–0.40 s cold vs ~0.05 s warm,
# which is exactly the five-request spike seen after every restart.
preload_app = True


def post_worker_init(worker):
    """Import the URLconf (and the layout templates) before serving traffic.

    Preloading imports the WSGI app, but Django resolves the URLconf lazily:
    the first request a worker serves pays ~230 ms to import every view, on
    top of its first template render — measured as 0.36–0.40 s dashboard
    responses from freshly restarted workers, then ~0.05 s once warm. Doing
    it here pays that cost at startup, before any user request.
    """
    try:
        from django.template.loader import get_template
        from django.urls import get_resolver

        # `get_resolver()` alone builds the resolver without importing the
        # URLconf: Django imports `config.urls` lazily on the first resolution,
        # which costs ~200 ms of CPU (drf-spectacular and friends) on the
        # worker's first request. Touching `url_patterns` forces that import.
        _ = get_resolver().url_patterns
        get_template("base.html")
        get_template("dashboard/home.html")

        # One anonymous request through the full stack (middleware, sessions,
        # CSRF, template rendering) so the first real visitor does not pay for
        # it. This calls the WSGI application directly with a hand-built
        # environ: no django.test import, and the response is discarded.
        from wsgiref.util import setup_testing_defaults

        from config.wsgi import application

        environ = {}
        setup_testing_defaults(environ)
        environ.update(
            REQUEST_METHOD="GET",
            PATH_INFO="/accounts/login/",
            QUERY_STRING="",
            SCRIPT_NAME="",
            SERVER_NAME="127.0.0.1",
            SERVER_PORT="80",
            HTTP_HOST="127.0.0.1",
        )
        environ["wsgi.url_scheme"] = "http"
        for _chunk in application(environ, lambda status, headers: None):
            pass
    except Exception:  # never stop a worker from serving over a warm-up
        pass
timeout = 60
graceful_timeout = 30
loglevel = "info"
accesslog = "-"
errorlog = "-"
proc_name = "itasset"
