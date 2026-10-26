"""Check the actual interpreter selected by py.exe, PATH or the registry."""
import sys

if sys.version_info < (3, 10):
    raise SystemExit(1)

# Match the server's runtime dependencies, including embedded distributions.
import copy
import datetime
import math
import ssl
import urllib.request
from http.cookies import SimpleCookie
import ctypes
import hmac
import json
import logging
import pathlib
import secrets
import threading
from http.server import ThreadingHTTPServer

print(json.dumps({"executable": sys.executable, "version": sys.version.split()[0]}))
