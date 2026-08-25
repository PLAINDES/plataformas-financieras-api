from datetime import datetime, timedelta

from app.api.main.analytics.router import build_occupation_profile_metrics


def test_profile_metrics_keep_latest_choice_per_device():
    now = datetime(2026, 8, 12, 10, 0, 0)
    rows = [
        (
            {
                "device_id": "device-1",
                "audience": "specialist",
                "role": "Tesorería",
                "company": "Kapital",
            },
            now,
        ),
        (
            {
                "device_id": "device-1",
                "audience": "specialist",
                "role": "Tesorería",
                "company": "Alicorp",
            },
            now + timedelta(minutes=1),
        ),
        (
            {
                "device_id": "device-2",
                "audience": "specialist",
                "role": "Contabilidad",
                "company": "Alicorp",
            },
            now,
        ),
    ]

    result = build_occupation_profile_metrics(rows)

    assert result.total_devices == 2
    assert [(item.label, item.count, item.percentage) for item in result.audiences] == [
        ("Especialistas", 2, 100.0),
        ("Empresas", 2, 100.0),
    ]
    assert [(item.label, item.count, item.percentage) for item in result.specialist_roles] == [
        ("Contabilidad", 1, 50.0),
        ("Tesorería", 1, 50.0),
    ]
    assert [(item.label, item.count, item.percentage) for item in result.company_names] == [
        ("Alicorp", 2, 100.0),
    ]


def test_profile_metrics_group_other_without_storing_detail():
    now = datetime(2026, 8, 12, 10, 0, 0)
    rows = [
        ({"device_id": "device-1", "audience": "specialist", "role": "Otro", "company": "Otro"}, now),
        ({"device_id": "device-2", "audience": "specialist", "role": "otro", "company": "otro"}, now),
        ({"device_id": "device-3", "audience": "specialist", "role": "Contabilidad", "company": "Kapital"}, now),
    ]

    result = build_occupation_profile_metrics(rows)

    assert result.total_devices == 3
    assert [(item.label, item.count, item.percentage) for item in result.specialist_roles] == [
        ("Otro", 2, 66.7),
        ("Contabilidad", 1, 33.3),
    ]
    assert [(item.label, item.count, item.percentage) for item in result.company_names] == [
        ("Otro", 2, 66.7),
        ("Kapital", 1, 33.3),
    ]
