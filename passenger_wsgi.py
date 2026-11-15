"""Точка входа для виртуального хостинга с Phusion Passenger (например, Timeweb).

Passenger ищет в корне сайта файл passenger_wsgi.py и объект `application`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import app as application  # noqa: E402,F401
