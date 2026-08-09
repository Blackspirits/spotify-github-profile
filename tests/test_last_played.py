import os
import sys
from unittest.mock import patch

# Keep api.view independent from a real Firebase configuration.
os.environ["TESTING"] = "true"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import view


def _track(name, duration_ms=180000):
    return {
        "name": name,
        "type": "track",
        "duration_ms": duration_ms,
        "uri": f"spotify:track:{name}",
        "artists": [{"name": "Test Artist"}],
        "album": {"images": [{"url": "https://example.com/cover.jpg"}] * 3},
    }


def _episode(name, duration_ms=240000):
    return {
        "name": name,
        "type": "episode",
        "duration_ms": duration_ms,
        "uri": f"spotify:episode:{name}",
        "show": {"publisher": "Test Show"},
        "images": [{"url": "https://example.com/cover.jpg"}] * 3,
    }


def test_active_playback_is_now_playing_and_preserves_progress():
    current = _track("Now")

    with patch.object(view, "get_access_token", return_value="token"), \
         patch.object(
             view.spotify,
             "get_now_playing",
             return_value={
                 "item": current,
                 "is_playing": True,
                 "currently_playing_type": "track",
                 "progress_ms": 42000,
             },
         ), \
         patch.object(view.spotify, "get_recently_play") as recent:
        item, is_now_playing, progress_ms, duration_ms = view.get_song_info(
            "uid", False
        )

    assert item["name"] == "Now"
    assert item["currently_playing_type"] == "track"
    assert is_now_playing is True
    assert progress_ms == 42000
    assert duration_ms == 180000
    recent.assert_not_called()


def test_paused_track_is_last_played_not_now_playing():
    paused = _track("Paused")

    with patch.object(view, "get_access_token", return_value="token"), \
         patch.object(
             view.spotify,
             "get_now_playing",
             return_value={
                 "item": paused,
                 "is_playing": False,
                 "currently_playing_type": "track",
                 "progress_ms": 60000,
             },
         ), \
         patch.object(view.spotify, "get_recently_play") as recent:
        item, is_now_playing, progress_ms, duration_ms = view.get_song_info(
            "uid", False
        )

    assert item["name"] == "Paused"
    assert item["currently_playing_type"] == "track"
    assert is_now_playing is False
    assert progress_ms is None
    assert duration_ms == 180000
    recent.assert_not_called()


def test_paused_episode_keeps_episode_type_for_recent_rendering():
    paused = _episode("Paused Episode")

    with patch.object(view, "get_access_token", return_value="token"), \
         patch.object(
             view.spotify,
             "get_now_playing",
             return_value={
                 "item": paused,
                 "is_playing": False,
                 "currently_playing_type": "episode",
             },
         ), \
         patch.object(view.spotify, "get_recently_play") as recent:
        item, is_now_playing, _, duration_ms = view.get_song_info("uid", False)

    assert item["name"] == "Paused Episode"
    assert item["currently_playing_type"] == "episode"
    assert is_now_playing is False
    assert duration_ms == 240000
    recent.assert_not_called()


def test_show_offline_still_hides_paused_content():
    paused = _track("Paused")

    with patch.object(view, "get_access_token", return_value="token"), \
         patch.object(
             view.spotify,
             "get_now_playing",
             return_value={
                 "item": paused,
                 "is_playing": False,
                 "currently_playing_type": "track",
             },
         ), \
         patch.object(view.spotify, "get_recently_play") as recent:
        result = view.get_song_info("uid", True)

    assert result == (None, False, None, None)
    recent.assert_not_called()


def test_recent_history_uses_latest_played_at_not_list_position():
    older = _track("Older")
    newest = _track("Newest")
    middle = _track("Middle")

    recent_payload = {
        "items": [
            {"played_at": "2026-08-09T08:00:00.000Z", "track": older},
            {"played_at": "2026-08-09T10:00:00.000Z", "track": newest},
            {"played_at": "2026-08-09T09:00:00.000Z", "track": middle},
        ]
    }

    with patch.object(view, "get_access_token", return_value="token"), \
         patch.object(view.spotify, "get_now_playing", return_value={}), \
         patch.object(view.spotify, "get_recently_play", return_value=recent_payload):
        first = view.get_song_info("uid", False)
        second = view.get_song_info("uid", False)

    assert first[0]["name"] == "Newest"
    assert second[0]["name"] == "Newest"
    assert first[1] is False
    assert first[2] is None
    assert first[3] == 180000


def test_missing_current_item_falls_back_to_recent_history_without_crashing():
    recent = _track("Fallback")

    with patch.object(view, "get_access_token", return_value="token"), \
         patch.object(
             view.spotify,
             "get_now_playing",
             return_value={
                 "item": None,
                 "is_playing": True,
                 "currently_playing_type": "track",
             },
         ), \
         patch.object(
             view.spotify,
             "get_recently_play",
             return_value={
                 "items": [
                     {
                         "played_at": "2026-08-09T10:00:00.000Z",
                         "track": recent,
                     }
                 ]
             },
         ):
        item, is_now_playing, _, _ = view.get_song_info("uid", False)

    assert item["name"] == "Fallback"
    assert is_now_playing is False


def test_recent_history_ignores_invalid_entries_and_handles_empty_history():
    valid = _track("Valid")

    payload = {
        "items": [
            None,
            {},
            {"played_at": "2026-08-09T11:00:00.000Z", "track": None},
            {"played_at": "2026-08-09T10:00:00.000Z", "track": valid},
        ]
    }

    with patch.object(view.spotify, "get_recently_play", return_value=payload):
        assert view._get_latest_recent_track("token")["name"] == "Valid"

    with patch.object(view.spotify, "get_recently_play", return_value={"items": []}):
        assert view._get_latest_recent_track("token") is None
