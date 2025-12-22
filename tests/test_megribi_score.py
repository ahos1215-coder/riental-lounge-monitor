from datetime import datetime, timedelta

from oriental.ml.megribi_score import clamp01, megribi_score, find_good_windows


def test_megribi_score_is_clamped():
    samples = [
        (0.0, 0.0, 1.0),
        (1.0, 0.7, 1.0),
        (2.0, 2.0, 2.0),
        (-1.0, -1.0, -1.0),
        (0.6, 0.9, 0.3),
    ]
    for female_ratio, occupancy_rate, stability in samples:
        score = megribi_score(
            female_ratio=female_ratio,
            occupancy_rate=occupancy_rate,
            stability=stability,
        )
        assert 0.0 <= score <= 1.0

    assert clamp01(-1) == 0.0
    assert clamp01(2.0) == 1.0


def test_find_good_windows_excludes_short_segments():
    base = datetime(2025, 1, 1, 19, 0, 0)
    points = [
        (base, 0.8, 0.7, 1.0),
        (base + timedelta(minutes=60), 0.8, 0.7, 1.0),
        (base + timedelta(minutes=120), 0.8, 0.7, 1.0),
        (base + timedelta(minutes=180), 0.2, 0.2, 1.0),
        (base + timedelta(minutes=240), 0.8, 0.7, 1.0),
    ]

    windows = find_good_windows(points, score_threshold=0.8, min_duration_minutes=120)
    assert len(windows) == 1
    window = windows[0]
    assert window["start"] == base
    assert window["end"] == base + timedelta(minutes=120)
    assert window["duration_minutes"] == 120.0
    assert 0.0 <= window["avg_score"] <= 1.0
