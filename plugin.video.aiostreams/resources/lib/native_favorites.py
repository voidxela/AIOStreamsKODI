"""Read AIOStreams entries from Kodi's native Favorites store.

Kodi owns all mutation of its favorites.  This module deliberately only reads
the documented JSON-RPC surface and accepts a narrow set of durable plugin
routes, so a bookmarked catalog or maintenance action never appears as media.
"""
from dataclasses import dataclass
import json
import re
import time
from urllib.parse import parse_qsl, urlparse


ADDON_HOST = 'plugin.video.aiostreams'
_TARGET_PATTERN = re.compile(r'plugin://plugin\.video\.aiostreams(?:/[^\s"\'),]*)?')
_SERIES_ACTIONS = frozenset(('show_seasons', 'browse_show'))


@dataclass(frozen=True)
class NativeFavorite:
    """A whitelisted native favorite, retaining Kodi's exact launch target."""

    target: str
    title: str
    thumbnail: str
    content_type: str
    action: str

    @property
    def is_folder(self):
        return self.content_type == 'series'


def _target_from_record(record):
    """Read the launch target from media/script paths or window parameters."""
    favorite_type = str(record.get('type') or '').lower()
    if favorite_type in ('media', 'script'):
        value = record.get('path') or ''
    elif favorite_type == 'window':
        value = record.get('windowparameter') or ''
    else:
        # The type is required by the current API.  Retain this fallback for
        # older Kodi records while still parsing only a whitelisted plugin URL.
        value = record.get('path') or record.get('windowparameter') or ''
    value = str(value).strip()
    if value.startswith('plugin://'):
        return value
    match = _TARGET_PATTERN.search(value)
    return match.group(0) if match else ''


def _content_type(action, params):
    declared = (params.get('content_type') or '').lower()
    if action in _SERIES_ACTIONS and declared in ('', 'series', 'show', 'shows', 'tvshow', 'tvshows'):
        return 'series'
    if action == 'play' and declared in ('movie', 'movies'):
        return 'movie'
    return None


def parse_favorite(record):
    """Return an AIOStreams movie/show favorite or ``None`` for any other URL."""
    target = _target_from_record(record)
    parsed = urlparse(target)
    if parsed.scheme != 'plugin' or parsed.netloc != ADDON_HOST:
        return None
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    action = params.get('action', '')
    content_type = _content_type(action, params)
    if not content_type:
        return None
    if content_type == 'series' and not params.get('meta_id'):
        return None
    if content_type == 'movie' and not any(
        params.get(key) for key in ('meta_id', 'media_id', 'imdb_id', 'tmdb_id')
    ):
        return None
    return NativeFavorite(
        target=target,
        title=str(record.get('title') or 'Unknown Title'),
        thumbnail=str(record.get('thumbnail') or ''),
        content_type=content_type,
        action=action,
    )


def list_aiostreams_favorites(execute_jsonrpc=None):
    """Return only whitelisted AIOStreams movie/show records from Kodi."""
    if execute_jsonrpc is None:
        import xbmc
        execute_jsonrpc = xbmc.executeJSONRPC
    request = json.dumps({
        'jsonrpc': '2.0',
        'id': 'aiostreams-favorites',
        'method': 'Favourites.GetFavourites',
        'params': {'properties': ['path', 'windowparameter', 'thumbnail']},
    })
    try:
        response = json.loads(execute_jsonrpc(request) or '{}')
        records = response.get('result', {}).get('favourites', [])
    except (TypeError, ValueError, AttributeError):
        return []
    return [favorite for record in records if (favorite := parse_favorite(record))]


def is_favorites_directory(path):
    """Return whether a Kodi container path is this add-on's Favorites view."""
    parsed = urlparse(path or '')
    if parsed.scheme != 'plugin' or parsed.netloc != ADDON_HOST:
        return False
    return dict(parse_qsl(parsed.query, keep_blank_values=True)).get('action') == 'favorites'


def favorites_signature(favorites):
    """Return the visible native data used to decide whether a redraw is needed."""
    return tuple(
        (favorite.target, favorite.title, favorite.thumbnail, favorite.content_type)
        for favorite in favorites
    )


class FavoritesDisplayPoller:
    """Refresh the open Favorites directory only after a native change."""

    def __init__(
        self, current_path, get_favorites, refresh, interval_seconds=10, clock=None,
    ):
        self._current_path = current_path
        self._get_favorites = get_favorites
        self._refresh = refresh
        self._interval_seconds = interval_seconds
        self._clock = clock or time.monotonic
        self._next_poll_at = 0
        self._signature = None

    def poll(self):
        """Poll once; return true only when the visible list was refreshed."""
        if not is_favorites_directory(self._current_path()):
            self._signature = None
            self._next_poll_at = 0
            return False
        now = self._clock()
        if now < self._next_poll_at:
            return False
        self._next_poll_at = now + self._interval_seconds
        try:
            signature = favorites_signature(self._get_favorites())
        except Exception:
            return False
        if self._signature is None:
            self._signature = signature
            return False
        if signature == self._signature:
            return False
        self._signature = signature
        self._refresh()
        return True
