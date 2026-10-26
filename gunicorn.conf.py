"""Serve Cloud Run requests using one shared Kia client per process."""

import os

bind = f"0.0.0.0:{int(os.environ.get('PORT', '8080'))}"
workers = 1
threads = 1
timeout = 180
accesslog = "-"
errorlog = "-"
# Log method/path/status only. Keep headers, query strings and bodies out.
access_log_format = '%(m)s %(U)s %(s)s %(L)s'
