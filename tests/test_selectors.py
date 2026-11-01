from unittest.mock import patch

import pytest
import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.application import create_app_session

from youtube_playlist_updater.ui import select_option, select_profiles


def run_keys(keys, default="b"):
    original = questionary.select
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        def terminal(*args, **kwargs):
            return original(*args, input=pipe, output=DummyOutput(), **kwargs)
        with patch("youtube_playlist_updater.ui.questionary.select", side_effect=terminal):
            return select_option("Choose", [("a", "First"), ("b", "Second"), ("c", "Third")], default)


def test_enter_accepts_default():
    assert run_keys("\r") == "b"


def test_up_arrow_changes_selection():
    assert run_keys("\x1b[A\r") == "a"


def test_down_arrow_changes_selection():
    assert run_keys("\x1b[B\r") == "c"


def test_ctrl_c_propagates_as_interruption():
    with pytest.raises(KeyboardInterrupt):
        run_keys("\x03")


def run_profile_keys(keys, profiles):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=DummyOutput()):
            return select_profiles(None, profiles)


def test_profile_menu_selects_any_combination(multi, origami):
    profiles = {"multi": multi, "origami": origami, "third": multi}
    assert run_profile_keys("\r\x1b[B\x1b[B\r\x1b[B\r", profiles) == [multi, multi]
    assert run_profile_keys("\x1b[B\r\x1b[B\x1b[B\r", profiles) == [origami]
    assert run_profile_keys("\r\x1b[B\r\x1b[B\r\x1b[B\r", profiles) == [multi, origami, multi]
    assert run_profile_keys("\x1b[A\x1b[A\r", profiles) == []
    assert run_profile_keys("\r\x1b[A\r", profiles) == []


def test_profile_menu_ctrl_c_cancels(multi):
    with pytest.raises(KeyboardInterrupt):
        run_profile_keys("\x03", {"multi": multi})
