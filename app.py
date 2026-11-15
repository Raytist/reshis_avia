"""«Решись Авиа: прогноз продаж» — веб-сервис (вариант C: страница + backend API).

Запуск локально:  python app.py   →  http://127.0.0.1:5000
Данные: data/my_forecast.csv (прогноз из ML-части), если его нет — data/seasonal_forecast.csv.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from forecast import ForecastError, ForecastService

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
LOGIN_RE = re.compile(r"^[A-Za-z0-9_.\-а-яА-ЯёЁ]{3,32}$")


def pick_forecast_file() -> Path:
    own = sorted(DATA.glob("*my_forecast.csv"))
    return own[0] if own else DATA / "seasonal_forecast.csv"


def load_secret_key(instance: Path) -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    key_file = instance / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


def create_app(db_path: Path | None = None, forecast_csv: Path | None = None) -> Flask:
    instance = BASE / "instance"
    instance.mkdir(exist_ok=True)
    app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
    app.config.update(
        SECRET_KEY=load_secret_key(instance),
        DB_PATH=str(db_path or instance / "users.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        JSON_AS_ASCII=False,
    )
    app.json.ensure_ascii = False
    service = ForecastService(forecast_csv or pick_forecast_file(), DATA / "routes.csv")

    # ---------- база пользователей ----------
    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    with app.app_context():
        db().executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                request TEXT NOT NULL,
                summary TEXT NOT NULL
            );
        """)
        db().commit()

    def error(message: str, status: int = 400):
        return jsonify({"error": message}), status

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return error("Войди или зарегистрируйся, чтобы считать прогноз.", 401)
            return view(*args, **kwargs)
        return wrapper

    def body() -> dict:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ---------- страницы ----------
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # ---------- регистрация и вход ----------
    @app.post("/api/register")
    def register():
        data = body()
        login = str(data.get("login", "")).strip()
        password = str(data.get("password", ""))
        if not LOGIN_RE.match(login):
            return error("Логин: от 3 до 32 символов — буквы, цифры, точка, дефис или подчёркивание.")
        if len(password) < 6:
            return error("Пароль должен быть не короче 6 символов.")
        try:
            cur = db().execute(
                "INSERT INTO users (login, password_hash, created_at) VALUES (?, ?, ?)",
                (login, generate_password_hash(password), now()))
            db().commit()
        except sqlite3.IntegrityError:
            return error("Такой логин уже занят.", 409)
        session.clear()
        session["user_id"], session["login"] = cur.lastrowid, login
        return jsonify({"login": login}), 201

    @app.post("/api/login")
    def login():
        data = body()
        row = db().execute("SELECT * FROM users WHERE login = ?",
                           (str(data.get("login", "")).strip(),)).fetchone()
        if row is None or not check_password_hash(row["password_hash"], str(data.get("password", ""))):
            return error("Неверный логин или пароль.", 401)
        session.clear()
        session["user_id"], session["login"] = row["id"], row["login"]
        return jsonify({"login": row["login"]})

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/me")
    def me():
        if "user_id" not in session:
            return jsonify({"login": None})
        return jsonify({"login": session["login"]})

    # ---------- прогноз ----------
    @app.get("/api/routes")
    def routes():
        return jsonify(service.routes_info())

    @app.post("/api/forecast")
    @login_required
    def forecast():
        data = body()
        try:
            result = service.forecast(data.get("origin", ""), data.get("destination", ""),
                                      data.get("date", ""), data.get("price", ""))
        except ForecastError as exc:
            return error(str(exc))
        if data.get("save", True):
            summary = (f"{result['origin']} → {result['destination']}, {result['date']}, "
                       f"{result['price']:.0f} ₽: купят {result['buy']} из {result['seats']}")
            db().execute("INSERT INTO queries (user_id, created_at, request, summary) VALUES (?, ?, ?, ?)",
                         (session["user_id"], now(), json.dumps(data, ensure_ascii=False), summary))
            db().commit()
        return jsonify(result)

    @app.get("/api/calendar/<route_code>")
    @login_required
    def calendar(route_code):
        try:
            return jsonify({"route": route_code, "days": service.calendar(route_code)})
        except ForecastError as exc:
            return error(str(exc), 404)

    @app.get("/api/history")
    @login_required
    def history():
        rows = db().execute(
            "SELECT created_at, request, summary FROM queries WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (session["user_id"],)).fetchall()
        return jsonify([{"created_at": r["created_at"], "request": json.loads(r["request"]),
                         "summary": r["summary"]} for r in rows])

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
