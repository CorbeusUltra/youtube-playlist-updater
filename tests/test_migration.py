import pytest
from youtube_playlist_updater.migration import playlist_state


def test_origami_preserves_selected_short_and_latest_date(origami):
    data = {"playlist_id":"beats-id","videos":[{"video_id":"v","title":"Previously selected short beat","published_at":"2026-06-21T17:08:21Z","duration":"1:15"}]}
    state = playlist_state(data,origami)
    record = state["decisions"]["v"]
    assert record["status"] == "add" and record["completed"] == ["beats"]
    assert record["video"]["seconds"] == 75
    assert state["baseline"] == "2026-06-21T17:08:21Z"
    assert state["initialized"] is False




def test_wrong_legacy_playlist_refused(origami):
    with pytest.raises(ValueError,match="different playlist"):
        playlist_state({"playlist_id":"wrong"},origami)


def test_import_v2_preserves_all_decisions_and_rejects_other_bindings(origami):
    from copy import deepcopy
    from youtube_playlist_updater.migration import convert_state
    state = playlist_state({"playlist_id": "beats-id", "videos": [{"video_id": "v", "title": "Selected", "published_at": "2026-06-01", "duration": "1:15"}]}, origami)
    before = deepcopy(state)
    assert convert_state(state, origami, origami.channel) == before
    assert state == before
    with pytest.raises(ValueError, match="different channel"):
        convert_state(state, origami, "other-channel")
    bad = {**state, "decisions": {"v": {"status": "invalid"}}}
    with pytest.raises(ValueError, match="Invalid decision"):
        convert_state(bad, origami, origami.channel)


def test_import_legacy_mono_playlist_refuses_multiple_destinations(multi):
    from youtube_playlist_updater.migration import convert_state
    with pytest.raises(ValueError, match="exactly one destination"):
        convert_state({"playlist_id": multi.targets[0].id}, multi, "channel")


def test_duration_rules_do_not_import_specialized_legacy_formats(origami):
    from youtube_playlist_updater.migration import convert_state
    with pytest.raises(ValueError, match="Unsupported legacy state"):
        convert_state({"version": 1}, origami, "channel")
