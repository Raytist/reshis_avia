import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forecast import ForecastError, ForecastService  # noqa: E402

DATA = ROOT / "data"


@pytest.fixture(scope="module")
def svc():
    return ForecastService(DATA / "seasonal_forecast.csv", DATA / "routes.csv")


def test_formula_matches_case(svc):
    # MOW-AER 2026-06-01: 0.5_base_demand = 775, base_price 9000, sensitivity 0.141, seats 900
    r = svc.forecast("Москва", "Сочи", "2026-06-01", 10000)
    assert r["want"] == round(775 - 0.141 * (10000 - 9000))   # 634
    assert r["buy"] == r["want"]
    assert r["seats"] == 900


def test_sales_capped_by_seats_and_zero(svc):
    cheap = svc.forecast("Москва", "Сочи", "2026-06-01", 0)
    assert cheap["want"] > cheap["seats"] and cheap["buy"] == cheap["seats"]
    pricey = svc.forecast("Москва", "Сочи", "2026-06-01", 100000)
    assert pricey["want"] < 0 and pricey["buy"] == 0
    assert pricey["warnings"]


def test_median_scenario_equals_simple_forecast(svc):
    r = svc.forecast("MOW", "AER", "2026-06-12", 9500)
    median = next(s for s in r["scenarios"] if s["quantile"] == "0.5")
    assert median["want"] == r["want"]
    wants = [s["want"] for s in r["scenarios"]]
    assert wants == sorted(wants)


@pytest.mark.parametrize("origin, dest, code", [
    ("москва", "Петербург", "MOW-LED"), ("МСК", "СПб", "MOW-LED"), ("Москва", "Санкт-Петербург", "MOW-LED"),
    ("MOW", "Минводы", "MOW-MRV"), ("Москва", "Адлер", "MOW-AER"), ("Moscow", "AER", None),
])
def test_city_aliases(svc, origin, dest, code):
    if code is None:
        with pytest.raises(ForecastError):
            svc.find_route(origin, dest)
    else:
        assert svc.find_route(origin, dest).code == code


def test_sellout_probability_bounds(svc):
    assert ForecastService.sellout_probability([10, 20, 30, 40, 50, 60, 70, 80, 90], 5)["label"] == "≥ 90%"
    assert ForecastService.sellout_probability([10, 20, 30, 40, 50, 60, 70, 80, 90], 95)["label"] == "≤ 10%"
    mid = ForecastService.sellout_probability([10, 20, 30, 40, 50, 60, 70, 80, 90], 50)
    assert mid["value"] == pytest.approx(0.5)


@pytest.mark.parametrize("args, message", [
    (("Сочи", "Москва", "2026-06-01", 9000), "только рейсы из Москвы"),
    (("Москва", "Казань", "2026-06-01", 9000), "нет в прогнозе"),
    (("Москва", "Сочи", "2026-08-01", 9000), "Прогноз есть на даты"),
    (("Москва", "Сочи", "12.06.2026", 9000), "ГГГГ-ММ-ДД"),
    (("Москва", "Сочи", "2026-06-01", -5), "отрицательной"),
    (("Москва", "Сочи", "2026-06-01", "abc"), "числом"),
    (("Москва", "Сочи", "2026-06-01", "nan"), "числом"),
    (("Москва", "Сочи", "2026-06-01", "inf"), "числом"),
    (("Москва", "Сочи", 12.5, 9000), "ГГГГ-ММ-ДД"),
    (("Москва", "Сочи", None, 9000), "ГГГГ-ММ-ДД"),
])
def test_bad_input(svc, args, message):
    with pytest.raises(ForecastError, match=message):
        svc.forecast(*args)


def test_robust_price_not_worse_than_median_price(svc):
    r = svc.forecast("Москва", "Сочи", "2026-06-12", 9000)
    route = svc.routes["MOW-AER"]
    flight = svc.flights[("MOW-AER", __import__("datetime").date(2026, 6, 12))]
    def profit(p):
        return (p - route.cost) * svc.expected_sales(route, flight, p)
    assert profit(r["robust_price"]["price"]) >= profit(round(r["model_price_median"], -2)) - 1


def test_calendar(svc):
    days = svc.calendar("MOW-LED")
    assert len(days) == 31 and all(0 <= d["load"] <= 1 for d in days)


# ---------- API ----------
@pytest.fixture()
def client(tmp_path):
    from app import create_app
    app = create_app(db_path=tmp_path / "t.db", forecast_csv=DATA / "seasonal_forecast.csv")
    app.config["TESTING"] = True
    return app.test_client()


def test_forecast_requires_login(client):
    r = client.post("/api/forecast", json={"origin": "Москва", "destination": "Сочи",
                                           "date": "2026-06-01", "price": 9000})
    assert r.status_code == 401


def test_register_login_forecast_history(client):
    assert client.post("/api/register", json={"login": "anna", "password": "secret1"}).status_code == 201
    assert client.post("/api/register", json={"login": "ANNA", "password": "secret1"}).status_code == 409
    client.post("/api/logout")
    assert client.post("/api/login", json={"login": "anna", "password": "wrong!!"}).status_code == 401
    assert client.post("/api/login", json={"login": "anna", "password": "secret1"}).status_code == 200
    r = client.post("/api/forecast", json={"origin": "Москва", "destination": "Сочи",
                                           "date": "2026-06-01", "price": 10000})
    assert r.status_code == 200 and r.get_json()["want"] == 634
    hist = client.get("/api/history").get_json()
    assert len(hist) == 1 and "Сочи" in hist[0]["summary"]
    assert client.post("/api/forecast", json={"origin": "Москва", "destination": "Сочи",
                                              "date": "2026-09-01", "price": 1}).status_code == 400


def test_register_validation(client):
    assert client.post("/api/register", json={"login": "a", "password": "secret1"}).status_code == 400
    assert client.post("/api/register", json={"login": "anna", "password": "123"}).status_code == 400
