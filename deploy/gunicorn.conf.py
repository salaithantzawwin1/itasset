"""Gunicorn config for the IT Asset Manager (DEVELOPMENT.md §24).

Server binds 127.0.0.1:8001; nginx (port 80/LAN) proxies to it.
"""

import multiprocessing

bind = "127.0.0.1:8001"
workers = max(2, multiprocessing.cpu_count() * 2 + 1)
timeout = 60
graceful_timeout = 30
loglevel = "info"
accesslog = "-"
errorlog = "-"
proc_name = "itasset"
