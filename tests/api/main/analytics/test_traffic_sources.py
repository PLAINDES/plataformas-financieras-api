from app.api.main.analytics.router import (
    normalize_utm,
    prettify_traffic_source,
    traffic_source_from_referrer,
)


def test_normalize_utm():
    assert normalize_utm(" LinkedIn ") == "linkedin"
    assert normalize_utm("Lanzamiento_Hoy") == "lanzamiento_hoy"
    assert normalize_utm("") is None
    assert normalize_utm(None) is None


def test_prettify_traffic_source():
    assert prettify_traffic_source("linkedin") == "LinkedIn"
    assert prettify_traffic_source("youtube") == "YouTube"
    assert prettify_traffic_source("facebook") == "Facebook"
    assert prettify_traffic_source("boletin") == "boletin"
    assert prettify_traffic_source("") == "Directo"
    assert prettify_traffic_source(None) == "Directo"


def test_traffic_source_from_referrer():
    assert traffic_source_from_referrer("https://www.linkedin.com/posts/abc") == "LinkedIn"
    assert traffic_source_from_referrer("https://youtu.be/xyz") == "YouTube"
    assert traffic_source_from_referrer("https://www.youtube.com/watch?v=1") == "YouTube"
    assert traffic_source_from_referrer("https://m.facebook.com/story") == "Facebook"
    assert traffic_source_from_referrer("https://www.google.com/search?q=x") == "Google"
    assert traffic_source_from_referrer("https://blog-ejemplo.com/post") == "Otros"
    assert traffic_source_from_referrer(None) == "Directo"
    assert traffic_source_from_referrer("") == "Directo"
