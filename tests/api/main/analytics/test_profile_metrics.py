from datetime import datetime, timedelta

from app.api.main.analytics.router import build_occupation_profile_metrics


def test_profile_metrics_keep_latest_choice_per_device():
    now = datetime(2026, 8, 12, 10, 0, 0)
    rows = [
        (
            {
                "device_id": "device-1",
                "audience": "student",
                "role": None,
            },
            now,
        ),
        (
            {
                "device_id": "device-1",
                "audience": "specialist",
                "role": "Tesorería",
            },
            now + timedelta(minutes=1),
        ),
        (
            {
                "device_id": "device-2",
                "audience": "student",
                "role": None,
            },
            now,
        ),
    ]

    result = build_occupation_profile_metrics(rows)

    assert result.total_devices == 2
    assert [(item.label, item.count, item.percentage) for item in result.audiences] == [
        ("Especialistas", 1, 50.0),
        ("Estudiantes", 1, 50.0),
    ]
    assert [(item.label, item.count, item.percentage) for item in result.specialist_roles] == [
        ("Tesorería", 1, 100.0),
    ]


def test_profile_metrics_group_other_without_storing_detail():
    now = datetime(2026, 8, 12, 10, 0, 0)
    rows = [
        ({"device_id": "device-1", "audience": "specialist", "role": "Otro"}, now),
        ({"device_id": "device-2", "audience": "specialist", "role": "otro"}, now),
        ({"device_id": "device-3", "audience": "specialist", "role": "Contabilidad"}, now),
        ({"audience": "student"}, now),
    ]

    result = build_occupation_profile_metrics(rows)

    assert result.total_devices == 3
    assert [(item.label, item.count, item.percentage) for item in result.specialist_roles] == [
        ("Otro", 2, 66.7),
        ("Contabilidad", 1, 33.3),
    ]
