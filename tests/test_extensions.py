from pathlib import Path

import pytest

from youtube_playlist_updater.config import load_config
from youtube_playlist_updater.policies.duration import DurationPolicy
from fakes import video


BASE = '''
[profiles.custom]
channel = "@example"
[profiles.custom.playlists.videos]
id = "PL_example"
'''


def write_config(root, text=BASE):
    path = root / "config.toml"
    path.write_text(text)
    return path


def test_duration_is_default_for_any_profile_name(tmp_path):
    path = write_config(tmp_path)
    profile = load_config(path)[0]["custom"]
    assert isinstance(profile.policy, DurationPolicy)
    assert profile.policy.classify(video("v", "Any upload", 1)).status == "add"


def test_no_implicit_discovery_of_local_python(tmp_path):
    local = tmp_path / ".local"
    local.mkdir()
    (local / "policies.py").write_text('raise AssertionError("Must not be imported")')
    assert isinstance(load_config(write_config(tmp_path))[0]["custom"].policy, DurationPolicy)


def test_extension_path_resolves_beside_config_not_current_directory(tmp_path, monkeypatch):
    external = tmp_path / "external"
    external.mkdir()
    extension = external / "rules.py"
    extension.write_text('''
from youtube_playlist_updater.policies.duration import DurationPolicy

def custom(settings, target_keys):
    return DurationPolicy(target_keys, 180, 0)

POLICY_FACTORIES = {"private": custom}
''')
    path = write_config(external, '[settings]\npolicy_extension = "rules.py"\n' + BASE.replace('channel = "@example"', 'channel = "@example"\npolicy = "private"'))
    monkeypatch.chdir(tmp_path)
    profile = load_config(path)[0]["custom"]
    assert profile.policy.classify(video("v", "Any upload", 179)).status == "ignore"
    assert profile.policy.classify(video("v", "Any upload", 180)).targets == ("videos",)
    assert not (external / "data").exists()


@pytest.mark.parametrize("body", [
    'POLICY_FACTORIES = {"duration": lambda settings, keys: None}',
    'POLICY_FACTORIES = {"private": None}',
    'POLICY_FACTORIES = []',
    'POLICY_FACTORIES = {"private": lambda settings, keys: object()}',
])
def test_invalid_extension_rejected_before_state_creation(tmp_path, body):
    (tmp_path / "rules.py").write_text(body)
    path = write_config(tmp_path, '[settings]\npolicy_extension = "rules.py"\n' + BASE.replace('channel = "@example"', 'channel = "@example"\npolicy = "private"'))
    with pytest.raises(ValueError):
        load_config(path)
    assert not (tmp_path / "data").exists()


def test_missing_explicit_extension_is_an_error(tmp_path):
    path = write_config(tmp_path, '[settings]\npolicy_extension = "missing.py"\n' + BASE)
    with pytest.raises(ValueError, match="extension not found"):
        load_config(path)


def test_public_src_contains_no_channel_specific_policy():
    source = Path(__file__).resolve().parents[1] / "src/youtube_playlist_updater/policies"
    assert {path.name for path in source.glob("*.py")} == {"__init__.py", "duration.py"}
