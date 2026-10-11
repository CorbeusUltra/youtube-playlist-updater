from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from fakes import FakeYouTube, video
from youtube_playlist_updater.engine import synchronize
from youtube_playlist_updater.models import Decision
from youtube_playlist_updater.policies.duration import DurationPolicy
from youtube_playlist_updater.storage import load


def run(api, profile, tmp_path, **kwargs):
    path = tmp_path / f"{profile.key}.json"
    return synchronize(api, profile, load(path), path, lambda *_: Decision("later"), **kwargs)


def empty(api):
    for target in api.profile.targets:
        api.playlists[target.id] = []


@pytest.mark.parametrize("mode,expected", [("all", 2), ("date", 1), ("future", 1)])
def test_empty_playlist_initializes_with_explicit_modes(origami, tmp_path, mode, expected):
    profile = replace(origami, initialization=mode, start_date="2026-10-07" if mode == "date" else None)
    api = FakeYouTube(profile, [video("new", "New beat")])
    empty(api)
    now = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    with patch("youtube_playlist_updater.engine.datetime") as clock:
        clock.now.return_value = now
        report = run(api, profile, tmp_path)
    assert len(report.added) == expected
    assert report.initialized
    assert load(tmp_path / "origami.json")["selection"]["mode"] == mode


def test_future_boundary_is_applied_to_later_discoveries(origami, tmp_path):
    profile = replace(origami, initialization="future")
    api = FakeYouTube(profile)
    now = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    with patch("youtube_playlist_updater.engine.datetime") as clock:
        clock.now.return_value = now
        run(api, profile, tmp_path)
    for vid, date in (("late_old", "2026-10-07T17:59:59Z"), ("boundary", "2026-10-07T18:00:00Z")):
        api.metadata[vid] = video(vid, "Beat", date=date)
        api.playlists["uploads"].insert(0, vid)
    report = run(api, profile, tmp_path)
    assert [v.id for v, _, _ in report.added] == ["boundary"]
    assert load(tmp_path / "origami.json")["decisions"]["late_old"]["status"] == "archive"


@pytest.mark.parametrize("zone,cutoff", [("UTC", "2026-06-01T00:00:00+00:00"), ("Europe/Zurich", "2026-05-31T22:00:00+00:00")])
def test_calendar_date_includes_local_midnight(origami, tmp_path, zone, cutoff):
    profile = replace(origami, initialization="date", start_date="2026-06-01", timezone=zone)
    before = "2026-05-31T21:59:59Z" if zone == "Europe/Zurich" else "2026-05-31T23:59:59Z"
    api = FakeYouTube(profile, [video("before", "Before", date=before), video("boundary", "Boundary", date=cutoff)])
    empty(api)
    report = run(api, profile, tmp_path)
    assert {v.id for v, _, _ in report.added} == {"boundary", "base"}
    assert load(tmp_path / "origami.json")["selection"]["cutoff"] == cutoff


def test_latest_requires_source_selection_and_offers_fallback(origami, tmp_path):
    api = FakeYouTube(origami, [video("new", "New beat")])
    api.metadata["base"] = replace(api.base, channel_id="another-channel")
    with pytest.raises(RuntimeError, match="No dated selection"):
        run(api, origami, tmp_path)
    assert not api.calls and not (tmp_path / "origami.json").exists()
    choices = []
    def choose(available):
        choices.append(available)
        return "all", None
    assert len(run(api, origami, tmp_path, choose_initialization=choose).added) == 1
    assert choices == [False]


def test_latest_boundary_excludes_equal_timestamp(origami, tmp_path):
    api = FakeYouTube(origami, [video("same", "Same date", date="2026-07-01T18:00:00Z")])
    assert not run(api, origami, tmp_path).added
    assert load(tmp_path / "origami.json")["decisions"]["same"]["status"] == "archive"


def test_missing_choice_cannot_write_state_or_playlist(origami, tmp_path):
    profile = replace(origami, initialization=None)
    api = FakeYouTube(profile)
    with pytest.raises(RuntimeError, match="Choose an initialization"):
        run(api, profile, tmp_path)
    assert not api.calls and not (tmp_path / "origami.json").exists()


def test_interactive_choice_and_simulation_do_not_persist(origami, tmp_path):
    profile = replace(origami, initialization=None)
    api = FakeYouTube(profile, [video("new", "New beat")])
    before = deepcopy(api.playlists)
    report = run(api, profile, tmp_path, dry_run=True, choose_initialization=lambda available: ("all", None))
    assert len(report.planned) == 1
    assert api.playlists == before and not api.calls and not api.stamps
    assert not (tmp_path / "origami.json").exists()


def test_all_preserves_previously_selected_short(origami, tmp_path):
    profile = replace(origami, initialization="all")
    api = FakeYouTube(profile)
    api.metadata["base"] = replace(api.base, seconds=1)
    assert not run(api, profile, tmp_path).pending
    assert load(tmp_path / "origami.json")["decisions"]["base"]["status"] == "add"


def test_pending_premiere_can_become_eligible_on_completion(origami, tmp_path):
    profile = replace(origami, initialization="date", start_date="2026-10-07")
    api = FakeYouTube(profile, [video("premiere", "Premiere", 0, "2026-10-06T18:00:00Z", broadcast="upcoming")])
    assert run(api, profile, tmp_path).waiting == 1
    api.metadata["premiere"] = video("premiere", "Premiere", date="2026-10-07T00:00:00Z")
    assert [v.id for v, _, _ in run(api, profile, tmp_path).added] == ["premiere"]


def test_explicit_archive_review_overrides_initial_boundary(origami, tmp_path):
    profile = replace(origami, initialization="date", start_date="2026-10-07")
    api = FakeYouTube(profile, [video("old", "Old beat", date="2026-06-01T00:00:00Z")])
    assert not run(api, profile, tmp_path).added
    assert [v.id for v, _, _ in run(api, profile, tmp_path, review_archives=True).added] == ["old"]


def test_existing_legacy_state_does_not_gain_a_new_boundary(origami, tmp_path):
    api = FakeYouTube(origami)
    run(api, origami, tmp_path)
    path = tmp_path / "origami.json"
    state = load(path)
    state.pop("selection")
    from youtube_playlist_updater.storage import save
    save(path, state)
    api.metadata["old_new_id"] = video("old_new_id", "Previously inaccessible", date="2026-06-01T00:00:00Z")
    api.playlists["uploads"].append("old_new_id")
    profile = replace(origami, initialization="future")
    assert len(run(api, profile, tmp_path).added) == 1
    after = load(path)
    assert "selection" not in after and after["baseline"] == state["baseline"]
    assert after["decisions"]["base"] == state["decisions"]["base"]


def test_arbitrary_generic_profile_routes_to_multiple_playlists(multi, tmp_path):
    targets = tuple(replace(t, order="published", youtube_sort=True) for t in multi.targets)
    profile = replace(multi, key="arbitrary", policy=DurationPolicy(("main", "extended")), targets=targets, initialization="all")
    api = FakeYouTube(profile, [video("new", "A video lasting 15 seconds", 15)])
    assert len(run(api, profile, tmp_path).added) == 2


@pytest.mark.parametrize("mode", ["future", "all", "date"])
def test_empty_channel_and_empty_playlist_can_initialize(origami, tmp_path, mode):
    profile = replace(origami, initialization=mode, start_date="2026-06-01" if mode == "date" else None)
    api = FakeYouTube(profile)
    api.metadata.clear()
    api.playlists = {**{t.id: [] for t in profile.targets}, "uploads": []}
    report = run(api, profile, tmp_path)
    assert report.initialized and not report.added and not report.errors
    assert load(tmp_path / "origami.json")["decisions"] == {}


def test_cancel_first_start_never_persists_selection(origami, tmp_path):
    profile = replace(origami, initialization=None)
    api = FakeYouTube(profile)
    def cancel(available):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(api, profile, tmp_path, choose_initialization=cancel)
    assert not api.calls and not (tmp_path / "origami.json").exists()
