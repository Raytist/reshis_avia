"""Логика прогноза продаж: без веба и без базы данных.

Формула из кейса:
    желают = base_demand − price_sensitivity × (цена − base_price)
    купят  = min(seats, max(0, желают))
Для простого прогноза берётся медиана 0.5_base_demand, для графика — все девять сценариев.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

QUANTILES = ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9"]
LEVELS = [float(q) for q in QUANTILES]
HUB = "MOW"
HUB_NAMES = {"москва", "mow", "msk", "мск"}


class ForecastError(ValueError):
    """Ошибка во входных данных: сообщение показывается пользователю как есть."""


@dataclass(frozen=True)
class Route:
    code: str            # MOW-AER
    origin: str          # Москва
    destination: str     # Сочи
    base_price: float
    cost: float          # расходы на пассажира
    sensitivity: float   # сколько пассажиров теряем на +1 ₽
    price_min: float
    price_max: float


@dataclass(frozen=True)
class Flight:
    route: str
    day: date
    seats: int
    base_demand: tuple[float, ...]   # 9 сценариев спроса при базовой цене
    best_price: tuple[float, ...]    # лучшая цена в каждом сценарии (из ML-части)


def _norm(text: str) -> str:
    return " ".join(str(text).strip().lower().replace("ё", "е").replace("-", " ").split())


# как люди на самом деле пишут города (ключ — после _norm)
CITY_ALIASES = {
    "петербург": "санкт петербург", "спб": "санкт петербург", "питер": "санкт петербург",
    "с петербург": "санкт петербург", "led": "санкт петербург",
    "минводы": "минеральные воды", "мин воды": "минеральные воды", "mrv": "минеральные воды",
    "aer": "сочи", "адлер": "сочи", "kgd": "калининград", "ovb": "новосибирск",
}


def _city(text: str) -> str:
    n = _norm(text)
    return CITY_ALIASES.get(n, n)


class ForecastService:
    def __init__(self, forecast_csv: Path, routes_csv: Path):
        self.routes: dict[str, Route] = {}
        with open(routes_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                origin, destination = [p.strip() for p in row["name"].split("—")]
                self.routes[row["route"]] = Route(
                    code=row["route"], origin=origin, destination=destination,
                    base_price=float(row["base_price"]), cost=float(row["cost_per_passenger"]),
                    sensitivity=float(row["price_sensitivity"]),
                    price_min=float(row["price_min"]), price_max=float(row["price_max"]),
                )
        self.flights: dict[tuple[str, date], Flight] = {}
        with open(forecast_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                day = date.fromisoformat(row["date"])
                self.flights[(row["route"], day)] = Flight(
                    route=row["route"], day=day, seats=int(float(row["seats"])),
                    base_demand=tuple(float(row[f"{q}_base_demand"]) for q in QUANTILES),
                    best_price=tuple(float(row[f"{q}_price"]) for q in QUANTILES),
                )
        days = sorted({d for _, d in self.flights})
        self.first_day, self.last_day = days[0], days[-1]
        self.source = Path(forecast_csv).name

    # ---------- поиск маршрута и рейса ----------
    def find_route(self, origin: str, destination: str) -> Route:
        o, d = _city(origin), _city(destination)
        if not o or not d:
            raise ForecastError("Укажи пункт отправления и пункт назначения.")
        for r in self.routes.values():
            if o in HUB_NAMES and d == _norm(r.destination):
                return r
        for r in self.routes.values():   # обратное направление: в прогнозе его нет
            if d in HUB_NAMES and o == _norm(r.destination):
                raise ForecastError(f"В прогнозе есть только рейсы из Москвы. Попробуй «Москва → {r.destination}».")
        if o not in HUB_NAMES:
            raise ForecastError("В прогнозе есть только рейсы из Москвы.")
        known = ", ".join(r.destination for r in self.routes.values())
        raise ForecastError(f"Маршрута «{origin} → {destination}» нет в прогнозе. Есть направления: {known}.")

    def find_flight(self, route: Route, day: date) -> Flight:
        flight = self.flights.get((route.code, day))
        if flight is None:
            raise ForecastError(
                f"Прогноз есть на даты с {self.first_day:%d.%m.%Y} по {self.last_day:%d.%m.%Y}.")
        return flight

    # ---------- расчёты ----------
    @staticmethod
    def wanting(route: Route, base_demand: float, price: float) -> float:
        """Сколько человек хотят купить билет по цене price (без ограничения по местам)."""
        return base_demand - route.sensitivity * (price - route.base_price)

    @staticmethod
    def buying(want: float, seats: int) -> float:
        return min(seats, max(0.0, want))

    @staticmethod
    def sellout_probability(wants: list[float], seats: int) -> dict:
        """Вероятность, что желающих не меньше, чем мест (самолёт распродан).
        Между квантилями — линейная интерполяция; за пределами 0.1–0.9 модель ничего точнее
        не знает, поэтому отвечаем границей: «не меньше 90%» или «не больше 10%»."""
        if seats <= wants[0]:
            return {"value": 0.9, "label": "≥ 90%"}
        if seats >= wants[-1]:
            return {"value": 0.1, "label": "≤ 10%"}
        for i in range(len(wants) - 1):
            lo, hi = wants[i], wants[i + 1]
            if lo <= seats <= hi:
                share = 0.0 if hi == lo else (seats - lo) / (hi - lo)
                level = LEVELS[i] + share * (LEVELS[i + 1] - LEVELS[i])
                p = 1 - level
                return {"value": round(p, 3), "label": f"{p * 100:.0f}%"}
        return {"value": 0.1, "label": "≤ 10%"}

    def expected_sales(self, route: Route, flight: Flight, price: float) -> float:
        """Средние продажи по девяти сценариям (каждый сценарий — равновероятный срез)."""
        sales = [self.buying(self.wanting(route, d, price), flight.seats) for d in flight.base_demand]
        return sum(sales) / len(sales)

    def best_price_under_uncertainty(self, route: Route, flight: Flight) -> dict:
        """Цена, при которой средняя прибыль по всем сценариям наибольшая (шаг 100 ₽)."""
        best = None
        price = route.price_min
        while price <= route.price_max + 1e-9:
            profit = (price - route.cost) * self.expected_sales(route, flight, price)
            if best is None or profit > best[1]:
                best = (price, profit)
            price += 100
        return {"price": round(best[0]), "expected_profit": round(best[1])}

    def forecast(self, origin: str, destination: str, day: str | date, price: float) -> dict:
        route = self.find_route(origin, destination)
        if not isinstance(day, date):
            try:
                day = date.fromisoformat(str(day).strip())
            except ValueError as exc:
                raise ForecastError("Дата должна быть в формате ГГГГ-ММ-ДД, например 2026-06-12.") from exc
        try:
            price = float(price)
        except (TypeError, ValueError) as exc:
            raise ForecastError("Цена должна быть числом в рублях.") from exc
        if not math.isfinite(price):
            raise ForecastError("Цена должна быть числом в рублях.")
        if price < 0:
            raise ForecastError("Цена не может быть отрицательной.")
        flight = self.find_flight(route, day)

        wants = [self.wanting(route, d, price) for d in flight.base_demand]
        median_want = wants[QUANTILES.index("0.5")]
        exp_sales = self.expected_sales(route, flight, price)
        warnings = []
        if not route.price_min <= price <= route.price_max:
            warnings.append(f"Цена вне допустимого диапазона маршрута: {route.price_min:.0f}–{route.price_max:.0f} ₽.")
        if median_want < 0:
            warnings.append("При такой цене желающих нет: формула дала отрицательный спрос, продажи равны 0.")
        return {
            "route": route.code,
            "origin": route.origin,
            "destination": route.destination,
            "date": day.isoformat(),
            "price": price,
            "seats": flight.seats,
            "want": round(median_want),
            "buy": round(self.buying(median_want, flight.seats)),
            "base_price": route.base_price,
            "scenarios": [
                {"quantile": q, "want": round(w), "buy": round(self.buying(w, flight.seats))}
                for q, w in zip(QUANTILES, wants)
            ],
            "sellout_probability": self.sellout_probability(wants, flight.seats),
            "expected_sales": round(exp_sales),
            "expected_profit": round((price - route.cost) * exp_sales),
            "model_price_median": round(flight.best_price[QUANTILES.index("0.5")]),
            "model_price_range": [round(flight.best_price[0]), round(flight.best_price[-1])],
            "robust_price": self.best_price_under_uncertainty(route, flight),
            "warnings": warnings,
        }

    def calendar(self, route_code: str) -> list[dict]:
        """Месяц по маршруту: медианный спрос, рекомендованная цена и заполняемость при ней."""
        route = self.routes.get(route_code)
        if route is None:
            raise ForecastError("Неизвестный маршрут.")
        out = []
        for (code, day), fl in sorted(self.flights.items(), key=lambda kv: kv[0][1]):
            if code != route_code:
                continue
            med = fl.base_demand[QUANTILES.index("0.5")]
            p = fl.best_price[QUANTILES.index("0.5")]
            sold = self.buying(self.wanting(route, med, p), fl.seats)
            out.append({
                "date": day.isoformat(),
                "seats": fl.seats,
                "demand_base": round(med),
                "price": round(p),
                "load": round(sold / fl.seats, 3) if fl.seats else 0,
                "sellout_at_base": self.sellout_probability(
                    [self.wanting(route, d, route.base_price) for d in fl.base_demand], fl.seats),
            })
        return out

    def routes_info(self) -> dict:
        return {
            "routes": [
                {"code": r.code, "origin": r.origin, "destination": r.destination,
                 "base_price": r.base_price, "price_min": r.price_min, "price_max": r.price_max,
                 "cost": r.cost, "sensitivity": r.sensitivity}
                for r in self.routes.values()
            ],
            "first_day": self.first_day.isoformat(),
            "last_day": self.last_day.isoformat(),
            "source": self.source,
        }
