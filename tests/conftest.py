import pytest
from youtube_playlist_updater.models import Profile, Target
from youtube_playlist_updater.policies.duration import DurationPolicy


@pytest.fixture
def multi():
    return Profile("multi", "Two destinations", "@example", (Target("main", "main-id", "First playlist"), Target("extended", "extended-id", "Second playlist")), DurationPolicy(("main", "extended")), initialization="latest")


@pytest.fixture
def origami():
    return Profile("origami", "Origami Beats", "UC-origami", (Target("beats", "beats-id", "Origami Beats", update_description=True),), DurationPolicy(("beats",), 60, 120), initialization="latest")
