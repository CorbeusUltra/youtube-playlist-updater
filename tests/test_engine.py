from copy import deepcopy
from dataclasses import replace

import pytest

from youtube_playlist_updater.engine import synchronize
from youtube_playlist_updater.models import Decision
from youtube_playlist_updater.storage import load
from fakes import FakeYouTube, video


def sync(api, profile, tmp_path, choice=lambda *_: Decision("later"), **kwargs):
    path = tmp_path / f"{profile.key}.json"
    return synchronize(api, profile, load(path), path, choice, **kwargs)


@pytest.mark.parametrize("profile_name,expected", [("multi",2),("origami",1)])
def test_same_engine_adds_and_deduplicates(profile_name, expected, request, tmp_path):
    profile = request.getfixturevalue(profile_name)
    api = FakeYouTube(profile, [video("new", "New upload")])
    assert len(sync(api, profile, tmp_path).added) == expected
    assert not sync(api, profile, tmp_path).added
    assert len(api.calls) == expected


def test_partial_failure_retries_only_missing_playlist(multi, tmp_path):
    api = FakeYouTube(multi, [video("new", "New upload")])
    api.fail_target = "extended"
    assert len(sync(api, multi, tmp_path).added) == 1
    api.fail_target = None
    assert len(sync(api, multi, tmp_path).added) == 1
    assert api.playlists["main-id"].count("new") == 1


def test_deferred_origami_choice_is_remembered(origami, tmp_path):
    api = FakeYouTube(origami, [video("new", "Beat ou Short ?", 90)])
    assert len(sync(api, origami, tmp_path).pending) == 1
    assert len(sync(api, origami, tmp_path, lambda *_: Decision("add", ("beats",), "full_video")).added) == 1
    assert not sync(api, origami, tmp_path).pending
    assert load(tmp_path / "origami.json")["decisions"]["new"]["nature"] == "full_video"


def test_ignored_short_is_not_asked_again(origami, tmp_path):
    api = FakeYouTube(origami, [video("new", "Promotion", 90)])
    sync(api, origami, tmp_path, lambda *_: Decision("ignore", nature="short_or_extract"))
    assert not sync(api, origami, tmp_path).pending
    assert not api.calls




def test_old_selection_not_reclassified(origami, tmp_path):
    api = FakeYouTube(origami)
    api.metadata["base"] = video("base", "Previously selected short video", 90, "2026-07-01T18:00:00Z")
    assert not sync(api, origami, tmp_path).pending


def test_removed_completed_video_is_not_reinserted(multi, tmp_path):
    api = FakeYouTube(multi, [video("new", "New upload")])
    sync(api, multi, tmp_path)
    api.playlists["main-id"].remove("new")
    report = sync(api, multi, tmp_path)
    assert not report.added and report.removed == 1
    assert len(api.calls) == 2


def test_metadata_change_reassesses_automatic_exclusion(origami, tmp_path):
    api = FakeYouTube(origami, [video("new", "Video", 59)])
    sync(api, origami, tmp_path)
    api.metadata["new"] = video("new", "Video", 90)
    assert len(sync(api, origami, tmp_path).pending) == 1


def test_live_is_rechecked_when_complete(multi, tmp_path):
    api = FakeYouTube(multi, [video("new", "New upload", broadcast="upcoming")])
    assert sync(api, multi, tmp_path).waiting == 1
    api.metadata["new"] = video("new", "New upload")
    assert len(sync(api, multi, tmp_path).added) == 2


def test_dry_run_changes_neither_api_nor_state(multi, tmp_path):
    api = FakeYouTube(multi, [video("new", "New upload")])
    before = deepcopy(api.playlists)
    assert len(sync(api, multi, tmp_path, dry_run=True).planned) == 2
    assert not (tmp_path / "multi.json").exists()
    assert before == api.playlists




def test_stamp_only_after_add_and_retry_if_failed(origami, tmp_path):
    api = FakeYouTube(origami)
    sync(api, origami, tmp_path)
    assert not api.stamps
    api.metadata["new"] = video("new", "New beat")
    api.playlists["uploads"].insert(0, "new")
    api.fail_description = True
    assert sync(api, origami, tmp_path).errors
    api.fail_description = False
    report = sync(api, origami, tmp_path)
    assert not report.added and report.descriptions == ["beats"]
    assert api.stamps == ["beats-id"]


def test_corrupt_state_fails_before_writing(multi, tmp_path):
    (tmp_path / "multi.json").write_text('{"version":2,"decisions":{"x":{"status":"bad"}}}')
    api = FakeYouTube(multi)
    with pytest.raises(RuntimeError, match="Invalid local state"):
        sync(api, multi, tmp_path)
    assert api.calls == []


def test_reconcile_insert_before_checkpoint_does_not_duplicate(multi, tmp_path):
    api = FakeYouTube(multi, [video("new", "New upload")])
    api.fail_target = "extended"
    sync(api, multi, tmp_path)
    api.playlists["extended-id"].append("new")
    api.fail_target = None
    report = sync(api, multi, tmp_path)
    assert not report.added
    assert api.playlists["extended-id"].count("new") == 1


def test_unavailable_pending_video_is_an_error(multi, tmp_path):
    api = FakeYouTube(multi, [video("new", "New upload")])
    api.fail_target = "extended"
    sync(api, multi, tmp_path)
    api.metadata.pop("new")
    assert sync(api, multi, tmp_path).errors


def test_bad_destination_from_choice_never_writes(origami, tmp_path):
    api = FakeYouTube(origami, [video("new", "Beat ?", 90)])
    with pytest.raises(RuntimeError, match="Invalid choice"):
        sync(api, origami, tmp_path, lambda *_: Decision("add", ("main",)))
    assert not api.calls


def test_optional_description_every_check_is_supported(origami, tmp_path):
    origami = replace(origami, targets=(replace(origami.targets[0], description_every_scan=True),))
    api = FakeYouTube(origami)
    assert sync(api, origami, tmp_path).descriptions == ["beats"]
    assert len(api.stamps) == 1
    assert api.last_stamp[0] is False
    assert api.last_stamp[1]


def test_successful_insert_tracks_modification_time(origami, tmp_path):
    api=FakeYouTube(origami,[video("new","New beat")])
    sync(api,origami,tmp_path)
    state=load(tmp_path/"origami.json")
    assert state["timestamps"]["beats"]["modified_at"]
    assert api.last_stamp[0] is True
    assert api.last_stamp[1] == state["last_scan_at"]


def test_old_selected_premiere_is_not_a_new_waiting_video(origami, tmp_path):
    api = FakeYouTube(origami)
    api.metadata["base"] = video("base", 'ORIGAMI TYPE BEAT " "', 0, "2022-10-09T12:31:38Z", broadcast="upcoming")
    report = sync(api, origami, tmp_path)
    assert report.waiting == 0 and not report.waiting_details
    assert report.preserved_count == 1
    assert not report.added


def test_genuine_new_premiere_has_an_identifiable_reason(origami, tmp_path):
    api = FakeYouTube(origami, [video("future", "New future beat", 0, broadcast="upcoming")])
    report = sync(api, origami, tmp_path)
    assert report.waiting == 1
    assert report.waiting_details[0].video.id == "future"
    assert "upcoming premiere" in report.waiting_details[0].reason


def test_successful_receipts_preserve_order_when_playlist_reads_remain_stale(origami, tmp_path):
    from youtube_playlist_updater.youtube import InsertResult
    class StaleLists(FakeYouTube):
        def items(self, pid):
            rows = super().items(pid)
            return rows if pid == "uploads" else [row for row in rows if row["video_id"] == "base"]
        def add_to_playlist(self, target, v, position):
            super().add_to_playlist(target, v, position)
            return InsertResult(True, True, {"item_id": f"item-{v.id}", "video_id": v.id, "title": v.title,
                                           "published_at": v.published_at, "position": position})
    api = StaleLists(origami, [video("first", "First", date="2026-10-01T00:00:00Z"), video("second", "Second", date="2026-10-02T00:00:00Z")])
    report = sync(api, origami, tmp_path)
    assert not report.errors and len(report.added) == 2
    assert api.calls == [("beats", "first", 1), ("beats", "second", 2)]
    state = load(tmp_path / "origami.json")
    assert all(state["decisions"][vid]["completed"] == ["beats"] for vid in ("first", "second"))
    assert not sync(api, origami, tmp_path).added
    assert len(api.calls) == 2  # Stale reads on the next run cannot reinsert confirmed entries.


def test_unconfirmed_write_survives_restart_without_a_second_insert(origami, tmp_path):
    from youtube_playlist_updater.youtube import UnconfirmedAddition
    class LostResponse(FakeYouTube):
        hidden = True
        def items(self, pid):
            rows = super().items(pid)
            return [row for row in rows if row["video_id"] != "new"] if self.hidden and pid != "uploads" else rows
        def add_to_playlist(self, target, v, position):
            super().add_to_playlist(target, v, position)
            raise UnconfirmedAddition("Simulated response lost after the write")
    api = LostResponse(origami, [video("new", "New beat")])
    assert sync(api, origami, tmp_path).errors
    record = load(tmp_path / "origami.json")["decisions"]["new"]
    assert record["completed"] == [] and record["pending_writes"] == ["beats"]
    assert sync(api, origami, tmp_path).errors
    assert len(api.calls) == 1
    before = (tmp_path / "origami.json").read_bytes()
    assert sync(api, origami, tmp_path, dry_run=True).errors
    assert (tmp_path / "origami.json").read_bytes() == before and len(api.calls) == 1
    api.hidden = False
    report = sync(api, origami, tmp_path)
    assert not report.errors and len(report.added) == 1
    record = load(tmp_path / "origami.json")["decisions"]["new"]
    assert record["completed"] == ["beats"] and "pending_writes" not in record
    assert len(api.calls) == 1 and api.playlists["beats-id"].count("new") == 1
    api.playlists["beats-id"].remove("new")
    assert sync(api, origami, tmp_path).removed == 1
    assert len(api.calls) == 1


def test_crash_after_remote_write_keeps_a_checkpoint_for_read_only_recovery(origami, tmp_path):
    class Interrupted(FakeYouTube):
        def add_to_playlist(self, target, v, position):
            # The journal must already be on disk before the API is called.
            record = load(tmp_path / "origami.json")["decisions"][v.id]
            assert record["pending_writes"] == [target.key]
            super().add_to_playlist(target, v, position)
            raise KeyboardInterrupt
    api = Interrupted(origami, [video("new", "New beat")])
    with pytest.raises(KeyboardInterrupt):
        sync(api, origami, tmp_path)
    report = sync(api, origami, tmp_path)
    assert not report.errors and len(report.added) == 1 and len(api.calls) == 1
    assert load(tmp_path / "origami.json")["decisions"]["new"]["completed"] == ["beats"]


def test_definite_rejection_clears_pending_checkpoint_for_a_later_retry(origami, tmp_path):
    api = FakeYouTube(origami, [video("new", "New beat")])
    api.fail_target = "beats"
    assert sync(api, origami, tmp_path).errors
    assert "pending_writes" not in load(tmp_path / "origami.json")["decisions"]["new"]
    api.fail_target = None
    assert len(sync(api, origami, tmp_path).added) == 1


def test_unconfirmed_attempt_requires_explicit_inclusion_to_retry(origami, tmp_path):
    from youtube_playlist_updater.youtube import UnconfirmedAddition
    class NoReceipt(FakeYouTube):
        fail_once = True
        def add_to_playlist(self, target, v, position):
            if self.fail_once:
                self.fail_once = False
                self.calls.append((target.key, v.id, position))
                raise UnconfirmedAddition("Uncertain request, no entry visible")
            return super().add_to_playlist(target, v, position)
    api = NoReceipt(origami, [video("new", "New beat")])
    assert sync(api, origami, tmp_path).errors
    assert sync(api, origami, tmp_path).errors and len(api.calls) == 1
    assert sync(api, origami, tmp_path, review_video="new").pending
    assert load(tmp_path / "origami.json")["decisions"]["new"]["pending_writes"] == ["beats"]
    decision = lambda *_: Decision("add", ("beats",), "full_video")
    report = sync(api, origami, tmp_path, decision, review_video="new")
    assert not report.errors and len(report.added) == 1 and len(api.calls) == 2


@pytest.mark.parametrize("pending", [["unknown-destination"], ["beats"]])
def test_invalid_pending_checkpoint_stops_before_another_write(origami, tmp_path, pending):
    import json
    api = FakeYouTube(origami, [video("new", "New beat")])
    sync(api, origami, tmp_path)
    path = tmp_path / "origami.json"
    state = load(path)
    state["decisions"]["new"]["pending_writes"] = pending
    path.write_text(json.dumps(state))
    calls = list(api.calls)
    with pytest.raises(RuntimeError, match="Invalid local state"):
        sync(api, origami, tmp_path)
    assert api.calls == calls
