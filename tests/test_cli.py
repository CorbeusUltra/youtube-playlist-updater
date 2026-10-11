from unittest.mock import patch

from youtube_playlist_updater import cli
from youtube_playlist_updater.models import Report


def test_two_profiles_reuse_one_connection(tmp_path, multi, origami):
    with patch.object(cli.Path,"cwd",return_value=tmp_path), patch.object(cli,"load_config",return_value=({"multi":multi,"origami":origami},{})), patch.object(cli,"connect") as connect, patch.object(cli,"synchronize",return_value=Report()) as sync:
        assert cli.main(["--all","--non-interactive"]) == 0
        assert connect.call_count == 1
        assert sync.call_count == 2


def test_demo_needs_no_google_or_state(tmp_path, multi, origami):
    with patch.object(cli.Path,"cwd",return_value=tmp_path), patch.object(cli,"load_config",return_value=({"multi":multi,"origami":origami},{})), patch.object(cli,"connect") as connect:
        assert cli.main(["--all","--demo","--non-interactive"]) == 0
        connect.assert_not_called()
        assert not (tmp_path/"data").exists()


def test_profile_failure_does_not_prevent_other_family(tmp_path, multi, origami):
    with patch.object(cli.Path,"cwd",return_value=tmp_path), patch.object(cli,"load_config",return_value=({"multi":multi,"origami":origami},{})), patch.object(cli,"connect"), patch.object(cli,"synchronize",side_effect=[RuntimeError("Playlist inaccessible"),Report()]) as sync:
        assert cli.main(["--all","--non-interactive"]) == 1
        assert sync.call_count == 2


def test_shared_auth_failure_is_not_retried_for_each_profile(tmp_path, multi, origami):
    with patch.object(cli.Path,"cwd",return_value=tmp_path), patch.object(cli,"load_config",return_value=({"multi":multi,"origami":origami},{})), patch.object(cli,"connect",side_effect=RuntimeError("Authentication expired")) as connect:
        assert cli.main(["--all","--non-interactive"]) == 1
        assert connect.call_count == 1


def test_external_configuration_does_not_use_current_directory(tmp_path, monkeypatch):
    from pathlib import Path
    import shutil
    root = Path(__file__).resolve().parents[1]
    external = tmp_path / "external"
    external.mkdir()
    config = external / "config.toml"
    shutil.copy2(root / "config.example.toml", config)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with patch.object(cli, "connect") as connect:
        assert cli.main(["--config", str(config), "--all", "--demo", "--non-interactive"]) == 0
    connect.assert_not_called()
    assert not (external / "data").exists() and not (elsewhere / "data").exists()


def test_unspecified_automated_initialization_does_not_touch_auth_or_disk(tmp_path):
    from youtube_playlist_updater.models import Profile, Target
    from youtube_playlist_updater.policies.duration import DurationPolicy
    profile = Profile("custom", "Custom", "@channel", (Target("videos", "PL_custom", "Videos"),), DurationPolicy(("videos",)))
    with patch.object(cli.Path, "cwd", return_value=tmp_path), patch.object(cli, "load_config", return_value=({"custom": profile}, {})), patch.object(cli, "connect") as connect:
        assert cli.main(["--all", "--non-interactive"]) == 1
    connect.assert_not_called()
    assert not (tmp_path / "data").exists() and not (tmp_path / "credentials").exists()


def test_check_without_initialization_does_not_create_state(tmp_path, origami):
    from dataclasses import replace
    from fakes import FakeYouTube
    profile = replace(origami, initialization=None)
    with patch.object(cli.Path, "cwd", return_value=tmp_path), patch.object(cli, "load_config", return_value=({"origami": profile}, {})), patch.object(cli, "connect", return_value=FakeYouTube(profile)):
        assert cli.main(["--all", "--check", "--non-interactive"]) == 0
    assert not (tmp_path / "data/origami.json").exists()


def test_import_resolves_handle_and_preserves_legacy_source(tmp_path, origami):
    import json
    from dataclasses import replace
    from fakes import FakeYouTube
    from youtube_playlist_updater.storage import load
    profile = replace(origami, key="custom", channel="@channel")
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"playlist_id": "beats-id", "videos": [{"video_id": "v", "title": "Selected short", "duration": "1:15", "published_at": "2026-06-01T00:00:00Z"}]}))
    before = source.read_bytes()
    api = FakeYouTube(profile)
    with patch.object(cli.Path, "cwd", return_value=tmp_path), patch.object(cli, "load_config", return_value=({"custom": profile}, {})), patch.object(cli, "connect", return_value=api):
        assert cli.main(["--profile", "custom", "--import-state", str(source), "--non-interactive"]) == 0
    assert source.read_bytes() == before and not api.calls and not api.stamps
    state = load(tmp_path / "data/custom.json")
    assert state["channel_id"] == "channel"
    assert state["decisions"]["v"]["completed"] == ["beats"]
    assert "selection" not in state


def test_import_refuses_to_overwrite_before_auth(tmp_path, origami):
    directory = tmp_path / "data"
    directory.mkdir()
    destination = directory / "origami.json"
    destination.write_text("Existing state must remain untouched")
    with patch.object(cli.Path, "cwd", return_value=tmp_path), patch.object(cli, "load_config", return_value=({"origami": origami}, {})), patch.object(cli, "connect") as connect:
        assert cli.main(["--profile", "origami", "--import-state", str(tmp_path / "source.json"), "--non-interactive"]) == 1
    connect.assert_not_called()
    assert destination.read_text() == "Existing state must remain untouched"


def test_unknown_profile_is_reported_without_auth(tmp_path, origami):
    with patch.object(cli.Path, "cwd", return_value=tmp_path), patch.object(cli, "load_config", return_value=({"origami": origami}, {})), patch.object(cli, "connect") as connect:
        assert cli.main(["--profile", "missing", "--non-interactive"]) == 1
    connect.assert_not_called()
