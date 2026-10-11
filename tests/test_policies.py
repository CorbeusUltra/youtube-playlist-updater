import pytest
from youtube_playlist_updater.policies.duration import DurationPolicy
from fakes import video


@pytest.mark.parametrize("seconds,status", [(1,"ignore"),(59,"ignore"),(60,"review"),(61,"review"),(75,"review"),(119,"review"),(120,"review"),(121,"add"),(180,"add"),(181,"add")])
def test_configured_duration_boundaries(seconds, status):
    result = DurationPolicy(("videos",), 60, 120).classify(video("v", "Any upload", seconds))
    assert result.status == status
    assert result.targets == (("videos",) if status == "add" else ())


def test_titles_do_not_affect_duration_selection():
    policy = DurationPolicy(("videos",), 60, 120)
    for title in ("Interview", "Episode #78 (Teaser)", "#shorts", "Concert"):
        assert policy.classify(video("v", title, 121)).status == "add"


def test_disabled_review_adds_from_minimum_inclusive():
    policy = DurationPolicy(("videos",), 180, 0)
    assert policy.classify(video("v", "Video", 179)).status == "ignore"
    assert policy.classify(video("v", "Video", 180)).status == "add"
