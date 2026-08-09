import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import with the repository's testing Firestore path without leaking TESTING
# into the rest of the test process.
with patch.dict(os.environ, {"TESTING": "true"}):
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

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(
            view.spotify,
            "get_now_playing",
            return_value={
                "item": current,
                "is_playing": True,
                "currently_playing_type": "track",
                "progress_ms": 42000,
            },
        ),
        patch.object(view.spotify, "get_recently_play") as recent,
    ):
        item, is_now_playing, progress_ms, duration_ms = view.get_song_info(
            "uid", False
        )

    assert item["name"] == "Now"
    assert item["currently_playing_type"] == "track"
    assert is_now_playing is True
    assert progress_ms == 42000
    assert duration_ms == 180000
    recent.assert_not_called()


def test_legacy_payload_without_is_playing_remains_compatible():
    current = _track("Legacy")

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(
            view.spotify,
            "get_now_playing",
            return_value={
                "item": current,
                "currently_playing_type": "track",
                "progress_ms": 12000,
            },
        ),
        patch.object(view.spotify, "get_recently_play") as recent,
    ):
        item, is_now_playing, progress_ms, _ = view.get_song_info("uid", False)

    assert item["name"] == "Legacy"
    assert is_now_playing is True
    assert progress_ms == 12000
    recent.assert_not_called()


def test_paused_track_is_recently_played_not_now_playing():
    paused = _track("Paused")

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(
            view.spotify,
            "get_now_playing",
            return_value={
                "item": paused,
                "is_playing": False,
                "currently_playing_type": "track",
                "progress_ms": 60000,
            },
        ),
        patch.object(view.spotify, "get_recently_play") as recent,
    ):
        item, is_now_playing, progress_ms, duration_ms = view.get_song_info(
            "uid", False, "latest"
        )

    assert item["name"] == "Paused"
    assert item["currently_playing_type"] == "track"
    assert is_now_playing is False
    assert progress_ms is None
    assert duration_ms == 180000
    recent.assert_not_called()


def test_paused_episode_keeps_episode_type_for_recent_rendering():
    paused = _episode("Paused Episode")

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(
            view.spotify,
            "get_now_playing",
            return_value={
                "item": paused,
                "is_playing": False,
                "currently_playing_type": "episode",
            },
        ),
        patch.object(view.spotify, "get_recently_play") as recent,
    ):
        item, is_now_playing, _, duration_ms = view.get_song_info(
            "uid", False, "latest"
        )

    assert item["name"] == "Paused Episode"
    assert item["currently_playing_type"] == "episode"
    assert is_now_playing is False
    assert duration_ms == 240000
    recent.assert_not_called()


def test_show_offline_still_hides_paused_content():
    paused = _track("Paused")

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(
            view.spotify,
            "get_now_playing",
            return_value={
                "item": paused,
                "is_playing": False,
                "currently_playing_type": "track",
            },
        ),
        patch.object(view.spotify, "get_recently_play") as recent,
    ):
        result = view.get_song_info("uid", True, "latest")

    assert result == (None, False, None, None)
    recent.assert_not_called()


def test_latest_mode_uses_latest_played_at_not_list_position():
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

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(view.spotify, "get_now_playing", return_value={}),
        patch.object(view.spotify, "get_recently_play", return_value=recent_payload),
    ):
        first = view.get_song_info("uid", False, "latest")
        second = view.get_song_info("uid", False, "latest")

    assert first[0]["name"] == "Newest"
    assert second[0]["name"] == "Newest"
    assert first[1] is False
    assert first[2] is None
    assert first[3] == 180000


def test_default_mode_preserves_historical_random_fallback():
    first = {"played_at": "2026-08-09T09:00:00.000Z", "track": _track("First")}
    second = {"played_at": "2026-08-09T10:00:00.000Z", "track": _track("Second")}
    recent_payload = {"items": [first, second]}

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(view.spotify, "get_now_playing", return_value={}),
        patch.object(view.spotify, "get_recently_play", return_value=recent_payload),
        patch.object(view.random, "choice", return_value=first) as choice,
    ):
        item, is_now_playing, _, _ = view.get_song_info("uid", False)

    assert item["name"] == "First"
    assert is_now_playing is False
    choice.assert_called_once_with([first, second])


def test_missing_current_item_falls_back_to_latest_history_without_crashing():
    recent = _track("Fallback")

    with (
        patch.object(view, "get_access_token", return_value="token"),
        patch.object(
            view.spotify,
            "get_now_playing",
            return_value={
                "item": None,
                "is_playing": True,
                "currently_playing_type": "track",
            },
        ),
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
        ),
    ):
        item, is_now_playing, _, _ = view.get_song_info("uid", False, "latest")

    assert item["name"] == "Fallback"
    assert is_now_playing is False


def test_recent_history_ignores_invalid_entries_and_invalid_payloads():
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
        assert view._get_recent_track("token", "latest")["name"] == "Valid"

    with patch.object(view.spotify, "get_recently_play", return_value={"items": []}):
        assert view._get_recent_track("token", "latest") is None

    with patch.object(view.spotify, "get_recently_play", return_value=None):
        assert view._get_recent_track("token", "latest") is None


def test_recent_mode_query_parameter_is_validated_before_playback_lookup():
    with (
        patch.object(
            view,
            "get_song_info",
            return_value=(None, False, None, None),
        ) as get_song_info,
        patch.object(view, "make_svg", return_value="<svg></svg>"),
        view.app.test_client() as client,
    ):
        response = client.get("/?uid=test_user&show_offline=true&recent_mode=latest")
        assert response.status_code == 200
        get_song_info.assert_called_once_with("test_user", True, "latest")

        get_song_info.reset_mock()
        response = client.get("/?uid=test_user&show_offline=true&recent_mode=unknown")
        assert response.status_code == 200
        get_song_info.assert_called_once_with("test_user", True, "random")
