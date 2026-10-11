from unittest.mock import patch

import pytest
import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

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


def test_profile_menu_uses_profile_values(multi, origami):
    with patch("youtube_playlist_updater.ui.select_option", return_value="origami"):
        assert select_profiles(None, {"multi": multi, "origami": origami}) == [origami]
    with patch("youtube_playlist_updater.ui.select_option", return_value="all"):
        assert select_profiles(None, {"multi": multi, "origami": origami}) == [multi, origami]
    with patch("youtube_playlist_updater.ui.select_option", return_value="quit"):
        assert select_profiles(None, {"multi": multi, "origami": origami}) == []
