import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from googleapiclient.errors import HttpError

from youtube_playlist_updater.models import Target
from youtube_playlist_updater.youtube import UnconfirmedAddition, YouTube, duration_seconds
from fakes import video


def http_error(reason, status=400):
    return HttpError(SimpleNamespace(status=status, reason="Request failed"), json.dumps({"error":{"errors":[{"reason":reason}]}}).encode())


def test_shared_pagination_reads_all_pages():
    api = MagicMock()
    item = lambda vid, pos: {"id": f"item-{vid}", "snippet": {"title":vid,"position":pos}, "contentDetails":{"videoId":vid}}
    api.playlistItems().list().execute.side_effect = [{"items":[item("a",0)],"nextPageToken":"next"},{"items":[item("b",1)]}]
    assert [v["video_id"] for v in YouTube(api).items("pid")] == ["a","b"]


@pytest.mark.parametrize("reference,parameter", [("@example","forHandle"),("UC-example","id")])
def test_same_channel_resolver_handles_both(reference, parameter):
    api = MagicMock()
    api.channels().list().execute.return_value = {"items":[{"id":"channel","contentDetails":{"relatedPlaylists":{"uploads":"uploads"}}}]}
    assert YouTube(api).channel(reference) == ("channel","uploads")
    assert parameter in api.channels().list.call_args.kwargs


def test_existing_video_is_not_inserted():
    api = MagicMock()
    service = YouTube(api)
    service.items = lambda _: [{"video_id":"v"}]
    assert not service.add_to_playlist(Target("a","pid","Playlist"), video("v","Beat"), 0).inserted
    api.playlistItems().insert.assert_not_called()


def test_date_sort_fallback_has_no_position():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = [http_error("manualSortRequired"),{}]
    service = YouTube(api)
    reads = iter([[],[{"video_id":"v"}]])
    service.items = lambda _: next(reads)
    result = service.add_to_playlist(Target("a","pid","Playlist",youtube_sort=True), video("v","Beat"), 0)
    assert result.inserted and not result.positioned
    assert "position" not in api.playlistItems().insert.call_args.kwargs["body"]["snippet"]


def test_number_order_never_silently_falls_back():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = http_error("manualSortRequired")
    service = YouTube(api)
    service.items = lambda _: []
    with pytest.raises(RuntimeError, match="Manual"):
        service.add_to_playlist(Target("a","pid","Playlist","episode",False), video("v","Episode #78"), 0)


def test_response_lost_after_fallback_reconciles_without_retry():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = [http_error("manualSortRequired"),TimeoutError()]
    service = YouTube(api)
    reads = iter([[],[{"video_id":"v"}]])
    service.items = lambda _: next(reads)
    result = service.add_to_playlist(Target("a","pid","Playlist"), video("v","Beat"), 0)
    assert result.inserted and not result.positioned
    assert api.playlistItems().insert().execute.call_count == 2


def test_owner_validation_blocks_wrong_google_account():
    api = MagicMock()
    api.channels().list().execute.return_value = {"items":[{"id":"mine"}]}
    api.playlists().list().execute.return_value = {"items":[{"id":"pid","snippet":{"channelId":"other","title":"Playlist"}}]}
    with pytest.raises(RuntimeError,match="own"):
        YouTube(api).validate_targets({"a":"pid"})


def test_tracking_preserves_title_description_and_tags():
    api = MagicMock()
    api.playlists().list().execute.return_value = {"items":[{"snippet":{"title":"Title","description":"Existing text\n🔄 Last updated: old","tags":["tag"]}}]}
    assert not YouTube(api).update_tracking(Target("a", "pid", "Playlist"), "2026-10-07T10:00:00Z")
    snippet = api.playlists().update.call_args.kwargs["body"]["snippet"]
    assert snippet["title"] == "Title" and snippet["tags"] == ["tag"]
    assert "🔄 Last updated:" not in snippet["description"]
    assert snippet["description"].count("Last checked on:") == 1
    assert "Existing text" in snippet["description"]


@pytest.mark.parametrize("duration,seconds",[("PT11M14S",674),("PT2H21M",8460),("PT0S",0),("P1DT1H",90000)])
def test_duration(duration,seconds):
    assert duration_seconds(duration) == seconds


def test_check_replaces_old_two_line_format():
    api = MagicMock()
    api.playlists().list().execute.return_value = {"items":[{"snippet":{"title":"Title","description":"Text\nLast modified on: not recorded yet\nLast checked on: old"}}]}
    YouTube(api).update_tracking(Target("a", "pid", "Playlist"), "2026-10-07T10:00:00Z")
    description=api.playlists().update.call_args.kwargs["body"]["snippet"]["description"]
    assert description == "Text\n\nLast checked on: 7 October 2026 at 12:00 CEST"


def test_addition_uses_updated_marker():
    api=MagicMock()
    api.playlists().list().execute.return_value={"items":[{"snippet":{"title":"Title","description":"Text\nLast checked on: old"}}]}
    assert YouTube(api).update_tracking(Target("a","pid","Playlist"), "2026-10-07T10:00:00Z", changed=True)
    assert "Last updated on:" in api.playlists().update.call_args.kwargs["body"]["snippet"]["description"]


def test_managed_body_change_is_updated_and_next_check_is_checked():
    api=MagicMock()
    response={"items":[{"snippet":{"title":"Title","description":"Outdated counts\nLast checked on: old"}}]}
    api.playlists().list().execute.return_value=response
    target=Target("a","pid","Playlist", description="Concise current description")
    assert YouTube(api).update_tracking(target,"2026-10-07T10:00:00Z")
    body=api.playlists().update.call_args.kwargs["body"]["snippet"]
    assert body["description"].startswith("Concise current description\n\nLast updated on:")
    api.playlists().list().execute.return_value={"items":[{"snippet":body}]}
    assert not YouTube(api).update_tracking(target,"2026-10-07T11:00:00Z")
    assert "Last checked on:" in api.playlists().update.call_args.kwargs["body"]["snippet"]["description"]


def test_escaped_legacy_newlines_do_not_accumulate_tracking_lines():
    api=MagicMock()
    original="Text"+r"\n\nLast modified on: old\nLast checked on: old"
    api.playlists().list().execute.return_value={"items":[{"snippet":{"title":"Title","description":original}}]}
    assert not YouTube(api).update_tracking(Target("a","pid","Playlist"),"2026-10-07T10:00:00Z")
    description=api.playlists().update.call_args.kwargs["body"]["snippet"]["description"]
    assert description=="Text\n\nLast checked on: 7 October 2026 at 12:00 CEST"


def test_description_tracking_uses_configured_timezone():
    api = MagicMock()
    api.playlists().list().execute.return_value = {"items": [{"snippet": {"title": "Title", "description": "Text"}}]}
    YouTube(api).update_tracking(Target("a", "pid", "Playlist", timezone="UTC"), "2026-10-07T10:00:00Z")
    assert "7 October 2026 at 10:00 UTC" in api.playlists().update.call_args.kwargs["body"]["snippet"]["description"]


def receipt(pid="pid", vid="v", position=0):
    return {"id": "created-item", "snippet": {"playlistId": pid, "position": position,
            "resourceId": {"kind": "youtube#video", "videoId": vid}}}


def test_success_receipt_confirms_write_without_rereading_stale_playlist():
    api = MagicMock()
    api.playlistItems().insert().execute.return_value = receipt(position=3)
    service = YouTube(api)
    service.items = MagicMock(return_value=[])
    result = service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 3)
    assert result.inserted and result.item["item_id"] == "created-item"
    assert result.item["position"] == 3
    assert service.items.call_count == 1  # Only the duplicate check before insertion.
    api.playlistItems().insert().execute.assert_called_once_with(num_retries=0)


def test_lost_response_waits_for_visibility_without_resending_write():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = TimeoutError()
    service = YouTube(api)
    service.items = MagicMock(side_effect=[[], [], [], [{"video_id": "v", "position": 0}]])
    with patch("youtube_playlist_updater.youtube.sleep") as wait:
        result = service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 0)
    assert result.inserted and service.items.call_count == 4
    assert wait.call_count == 2
    api.playlistItems().insert().execute.assert_called_once_with(num_retries=0)


def test_invisible_lost_write_stays_uncertain_after_bounded_reads():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = TimeoutError()
    service = YouTube(api)
    service.items = MagicMock(return_value=[])
    with patch("youtube_playlist_updater.youtube.sleep") as wait:
        with pytest.raises(UnconfirmedAddition, match="awaiting confirmation"):
            service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 0)
    assert service.items.call_count == 5  # Preflight plus four reconciliation reads.
    assert wait.call_count == 3
    api.playlistItems().insert().execute.assert_called_once_with(num_retries=0)


@pytest.mark.parametrize("response", [{}, receipt(pid="other"), receipt(vid="other"), {**receipt(), "id": ""}])
def test_missing_or_mismatched_receipt_cannot_confirm_a_write(response):
    api = MagicMock()
    api.playlistItems().insert().execute.return_value = response
    service = YouTube(api)
    service.items = MagicMock(return_value=[])
    with patch("youtube_playlist_updater.youtube.sleep"):
        with pytest.raises(UnconfirmedAddition):
            service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 0)
    api.playlistItems().insert().execute.assert_called_once_with(num_retries=0)


def test_server_error_reconciles_but_definite_rejection_does_not():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = http_error("backendError", 503)
    service = YouTube(api)
    service.items = MagicMock(side_effect=[[], [{"video_id": "v"}]])
    assert service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 0).inserted
    api.playlistItems().insert().execute.side_effect = http_error("playlistItemsNotAccessible", 403)
    service.items = MagicMock(return_value=[])
    with pytest.raises(HttpError):
        service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 0)
    assert service.items.call_count == 1


def test_explicit_reconciliation_never_issues_an_insert():
    api = MagicMock()
    service = YouTube(api)
    service.items = MagicMock(side_effect=[[], [{"video_id": "v"}]])
    with patch("youtube_playlist_updater.youtube.sleep"):
        assert service.confirm_addition(Target("a", "pid", "Playlist"), video("v", "Beat")).inserted
    api.playlistItems().insert.assert_not_called()


def test_confirmation_read_errors_do_not_turn_an_uncertain_write_into_a_retry():
    api = MagicMock()
    api.playlistItems().insert().execute.side_effect = TimeoutError()
    service = YouTube(api)
    service.items = MagicMock(side_effect=[[], *[KeyError("Unexpected playlist response") for _ in range(4)]])
    with patch("youtube_playlist_updater.youtube.sleep"):
        with pytest.raises(UnconfirmedAddition, match="Read error"):
            service.add_to_playlist(Target("a", "pid", "Playlist"), video("v", "Beat"), 0)
    api.playlistItems().insert().execute.assert_called_once_with(num_retries=0)
