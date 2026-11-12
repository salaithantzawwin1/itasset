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
timeout = 60
graceful_timeout = 30
loglevel = "info"
accesslog = "-"
errorlog = "-"
proc_name = "itasset"
