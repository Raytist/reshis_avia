# Точка входа для виртуального хостинга Timeweb (Apache + mod_wsgi).
# Этот файл и .htaccess кладутся в public_html, а код сайта — в папку ВНЕ public_html,
# чтобы база пользователей и секретный ключ не были доступны по ссылке.
#
# Замените в путях ниже:  u    — первая буква вашего логина Timeweb,
#                         user — ваш логин,
#                         python3.10 — версия Python на сервере (Ubuntu 22.04 → 3.10).
import sys

APP_DIR = "/home/u/user/reshis-avia"                          # куда загружен код сайта
VENV_SITE = "/home/u/user/venv/lib/python3.10/site-packages"   # библиотеки из виртуального окружения

sys.path.insert(0, VENV_SITE)
sys.path.insert(0, APP_DIR)

from app import app as application  # noqa: E402
