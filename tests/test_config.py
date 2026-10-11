from pathlib import Path

import pytest

from youtube_playlist_updater.config import load_config
from youtube_playlist_updater.policies.duration import DurationPolicy
from fakes import video

BASE = '''
[profiles.channel_one]
policy = "duration"
channel = "@example"
[profiles.channel_one.playlists.destination]
id = "PL_example"
'''


def config(tmp_path, text=BASE):
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return load_config(path)[0]


def test_arbitrary_profile_selects_every_finished_duration_by_default(tmp_path):
    profile = config(tmp_path)["channel_one"]
    assert profile.timezone == "UTC" and profile.initialization is None
    assert profile.targets[0].timezone == "UTC"
    for seconds in (1, 59, 90, 121, 7200):
        assert profile.policy.classify(video("v", "Any title", seconds)).targets == ("destination",)
    assert not profile.targets[0].update_description


def test_configured_thresholds_and_multiple_destinations(tmp_path):
    text = BASE.replace('channel = "@example"', 'channel = "@example"\nminimum_seconds = 60\nreview_max_seconds = 120')
    text += '\n[profiles.channel_one.playlists.second]\nid = "PL_second"\n'
    profile = config(tmp_path, text)["channel_one"]
    assert profile.policy.classify(video("v", "Video", 59)).status == "ignore"
    for seconds in (60, 120):
        assert profile.policy.classify(video("v", "Video", seconds)).status == "review"
    assert profile.policy.classify(video("v", "Video", 121)).targets == ("destination", "second")


@pytest.mark.parametrize("change", [
    lambda s: s.replace("channel_one", "../escape"),
    lambda s: s.replace("channel_one", "all"),
    lambda s: s.replace('policy = "duration"', 'policy = "unknown"'),
    lambda s: s.replace('channel = "@example"', 'channel = "bad"'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\nlabel = false'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\ncredential_store = "../escape"'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\nminimum_seconds = true'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\nminimum_seconds = -1'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\nminimum_seconds = 60\nreview_max_seconds = 30'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\ninitialization = "unknown"'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\ninitialization = "date"\nstart_date = "2026-02-30"'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\ninitialization = "date"'),
    lambda s: s.replace('channel = "@example"', 'channel = "@example"\nstart_date = "2026-06-01"'),
    lambda s: s.replace('id = "PL_example"', 'id = "PL_example"\norder = "episode"'),
    lambda s: s.replace('id = "PL_example"', 'id = "PL_example"\nupdate_description = "false"'),
    lambda s: '[settings]\ntimezone = "invalid/zone"\n' + s,
    lambda s: '[auth]\noauth_port = 65536\n' + s,
    lambda s: s + '\n[profiles.channel_one.playlists.second]\nid = "PL_example"\n',
])
def test_invalid_configuration_rejected(tmp_path, change):
    with pytest.raises(ValueError):
        config(tmp_path, change(BASE))


def test_public_examples_parse_without_description_writes():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "config.example.toml", root / "examples/config.origami.toml", root / "examples/config.ego.toml"):
        profiles, _ = load_config(path)
        for profile in profiles.values():
            assert isinstance(profile.policy, DurationPolicy)
            assert profile.initialization is None and profile.start_date is None
            assert profile.timezone == "UTC"
            for target in profile.targets:
                assert target.id == "PL_REPLACE_WITH_YOUR_PLAYLIST_ID"
                assert not target.update_description and not target.description_every_scan
                assert target.order == "published" and target.youtube_sort
    origami = load_config(root / "examples/config.origami.toml")[0]["origami"]
    assert isinstance(origami.policy, DurationPolicy)
    assert origami.channel == "UCmcF_CZ4oA3MkFdUZ5friXA"
    assert origami.targets[0].id == "PL_REPLACE_WITH_YOUR_PLAYLIST_ID"
    for seconds, status in ((59, "ignore"), (60, "review"), (120, "review"), (121, "add")):
        assert origami.policy.classify(video("v", "Beat", seconds)).status == status


def test_public_ego_example_reviews_through_three_minutes():
    root = Path(__file__).resolve().parents[1]
    profile = load_config(root / "examples/config.ego.toml")[0]["ego"]
    assert profile.channel == "@ego_one"
    assert profile.policy.minimum_seconds == 0
    assert profile.policy.review_max_seconds == 180
    for seconds in (1, 60, 120, 180):
        assert profile.policy.classify(video("v", "Upload", seconds)).status == "review"
    assert profile.policy.classify(video("v", "Upload", 181)).targets == ("videos",)


def test_old_profile_configuration_keeps_duration_rules(tmp_path):
    text = BASE.replace("channel_one", "origami").replace('policy = "duration"\n', '').replace('channel = "@example"', 'channel = "@example"\nreview_min_seconds = 60\nreview_max_seconds = 120')
    profile = config(tmp_path, text)["origami"]
    assert isinstance(profile.policy, DurationPolicy)
    assert profile.policy.classify(video("v", "Beat", 59)).status == "ignore"
    assert profile.policy.classify(video("v", "Beat", 90)).status == "review"


def test_explicit_policy_on_origami_key_uses_public_defaults(tmp_path):
    profile = config(tmp_path, BASE.replace("channel_one", "origami"))["origami"]
    assert profile.policy.classify(video("v", "Beat", 59)).status == "add"


def test_missing_configuration_explains_setup(tmp_path):
    with pytest.raises(RuntimeError, match="config.example.toml"):
        load_config(tmp_path / "missing.toml")
