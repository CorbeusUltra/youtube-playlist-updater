from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from youtube_playlist_updater.models import Decision, Report
from youtube_playlist_updater.ui import chooser, show_report
from fakes import video


@pytest.mark.parametrize("profile_name,answer,nature,action", [("origami","1","full_video","add"),("origami","2","short_or_extract","ignore")])
def test_same_menu_uses_policy_options(request, profile_name, answer, nature, action):
    profile = request.getfixturevalue(profile_name)
    output = StringIO()
    console = Console(file=output, width=110)
    console.input = lambda *args, **kwargs: answer
    v = video("v", "Video to review", 90)
    with patch("youtube_playlist_updater.ui.select_option", return_value=answer):
        decision = chooser(console, profile)(v, profile.policy.classify(v))
    assert decision.action == action and decision.nature == nature
    assert v.url in output.getvalue() and "1:30" in output.getvalue()


def test_open_video_returns_to_same_decision(origami):
    console = Console(file=StringIO())
    answers = iter(["o", "1"])
    console.input = lambda *args, **kwargs: next(answers)
    v = video("v", "Beat ?", 90)
    with patch("youtube_playlist_updater.ui.webbrowser.open", return_value=True) as opener, patch("youtube_playlist_updater.ui.select_option", side_effect=["o", "1"]):
        decision = chooser(console, origami)(v, origami.policy.classify(v))
    opener.assert_called_once_with(v.url)
    assert decision.targets == ("beats",)




def test_noninteractive_never_prompts(origami):
    console = Console(file=StringIO())
    console.input = lambda *args, **kwargs: pytest.fail("No prompt expected")
    v = video("v", "Beat ?", 90)
    assert chooser(console, origami, False)(v, origami.policy.classify(v)).action == "later"


def test_pending_report_has_link_and_no_false_success(origami):
    output = StringIO()
    v = video("v", "Beat ?", 90)
    show_report(Console(file=output), origami, Report(pending=[v]))
    assert v.url in output.getvalue()
    assert "waiting for your decision" in output.getvalue()
    assert "No new releases" not in output.getvalue()


def test_partial_failure_report_leads_with_incomplete(origami):
    output = StringIO()
    show_report(Console(file=output), origami, Report(added=[(video("v", "Beat"), "beats", False)], errors=["Quota exhausted"]))
    assert "Incomplete update" in output.getvalue()
    assert "Automatic update" not in output.getvalue()


def test_check_only_explains_what_changed(origami):
    output = StringIO()
    show_report(Console(file=output, width=150), origami, Report(descriptions=["beats"]))
    text = output.getvalue()
    assert "Last checked on" in text
    assert "Verification date" in text


def test_waiting_report_identifies_video_and_reason(origami):
    from youtube_playlist_updater.models import DeferredVideo
    output = StringIO()
    v = video("future", "Future beat", 0)
    show_report(Console(file=output), origami, Report(waiting=1, waiting_details=[DeferredVideo(v, "Upcoming premiere")]))
    assert "Future beat" in output.getvalue()
    assert v.url in output.getvalue()
    assert "Upcoming premiere" in output.getvalue()


def test_initialization_menu_omits_unavailable_latest_and_validates_date(origami):
    from youtube_playlist_updater.ui import initialization_chooser
    console = Console(file=StringIO())
    with patch("youtube_playlist_updater.ui.select_option", return_value="date") as select, patch("youtube_playlist_updater.ui.Prompt.ask", side_effect=["2026-02-30", "2026-06-01"]):
        assert initialization_chooser(console, origami)(False) == ("date", "2026-06-01")
    assert "latest" not in dict(select.call_args.args[1])


def test_initialization_cancel_preserves_interruption(origami):
    from youtube_playlist_updater.ui import initialization_chooser
    console = Console(file=StringIO())
    with patch("youtube_playlist_updater.ui.select_option", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            initialization_chooser(console, origami)(True)
