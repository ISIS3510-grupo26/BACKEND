"""Pruebas de la BQ15: la hora del dia con menor espera reportada en cada restaurante."""
from tests.test_wait_times import at_time, client, report  # noqa: F401  (fixtures compartidas)

URL = "/api/v1/analytics/best-time-to-go"


def best_time(client, **params):
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    return body, {s["spotId"]: s for s in body["spots"]}


def test_best_and_worst_hour_use_local_time(client, at_time):
    at_time("2026-11-20T23:00:00+00:00")
    # Bogota es UTC-5: 13:00Z = 8 am local, 17:00Z = 12 m local.
    report(client, minutes=4, reported_at="2026-11-18T13:05:00Z")
    report(client, minutes=6, reported_at="2026-11-19T13:20:00Z")
    report(client, minutes=25, reported_at="2026-11-19T17:10:00Z")
    report(client, minutes=35, reported_at="2026-11-20T17:30:00Z")

    body, spots = best_time(client, tzOffsetMinutes=-300)
    nitro = spots["nitro-coffee"]
    assert body["question"].startswith("At what time of the day")
    assert body["totalReports"] == 4
    assert nitro["reports"] == 4
    assert (nitro["bestHour"], nitro["bestHourAvgMinutes"]) == (8, 5.0)
    assert (nitro["worstHour"], nitro["worstHourAvgMinutes"]) == (12, 30.0)
    assert [h["hour"] for h in nitro["byHour"]] == [8, 12]


def test_spot_without_reports_has_no_best_hour(client, at_time):
    at_time("2026-11-20T23:00:00+00:00")
    _, spots = best_time(client)
    assert len(spots) == 7
    assert spots["green-bowl-co"]["bestHour"] is None
    assert spots["green-bowl-co"]["byHour"] == []


def test_old_reports_and_thin_hours_are_left_out(client, at_time):
    at_time("2026-11-20T23:00:00+00:00")
    report(client, minutes=2, reported_at="2026-09-01T13:00:00Z")   # fuera de la ventana de 28 dias
    report(client, minutes=10, reported_at="2026-11-19T15:00:00Z")  # 10 am, un solo reporte
    report(client, minutes=20, reported_at="2026-11-19T19:00:00Z")  # 2 pm
    report(client, minutes=22, reported_at="2026-11-20T19:00:00Z")  # 2 pm

    body, spots = best_time(client, minReports=2)
    nitro = spots["nitro-coffee"]
    assert body["totalReports"] == 3
    assert nitro["bestHour"] == 14          # las 10 am no cuentan: un solo reporte
    assert len(nitro["byHour"]) == 2        # pero siguen en el detalle por hora
