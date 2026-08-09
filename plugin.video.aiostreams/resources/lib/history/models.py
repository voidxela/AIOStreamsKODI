"""Provider-neutral durable watch-history value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


def _value(value):
    value = str(value).strip() if value is not None else ''
    return value or None


def _namespaced_tmdb(value):
    value = _value(value)
    return 'tmdb:{}'.format(value) if value else None


@dataclass(frozen=True)
class HistoryMediaRef:
    """Identity required by a history provider, including episode parentage."""

    kind: str
    imdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    show_imdb_id: Optional[str] = None
    show_tmdb_id: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    metadata_id: Optional[str] = None
    origin_fingerprint: Optional[str] = None
    title: str = ''
    show_title: Optional[str] = None

    def __post_init__(self):
        kind = str(self.kind or '').lower()
        if kind == 'series':
            kind = 'episode'
        if kind not in ('movie', 'episode'):
            raise ValueError('History media kind must be movie or episode')
        object.__setattr__(self, 'kind', kind)
        for name in ('imdb_id', 'tmdb_id', 'show_imdb_id', 'show_tmdb_id',
                     'metadata_id', 'origin_fingerprint', 'show_title'):
            object.__setattr__(self, name, _value(getattr(self, name)))
        object.__setattr__(self, 'title', str(self.title or '').strip())
        for name in ('season', 'episode'):
            value = getattr(self, name)
            if value not in (None, ''):
                try:
                    object.__setattr__(self, name, int(value))
                except (TypeError, ValueError):
                    object.__setattr__(self, name, None)

    @property
    def show_key(self):
        """Stable identity for a series, independent of an episode IMDb ID."""
        if self.kind != 'episode':
            return None
        if self.show_imdb_id:
            return 'show:imdb:{}'.format(self.show_imdb_id)
        if self.show_tmdb_id:
            return 'show:{}'.format(_namespaced_tmdb(self.show_tmdb_id))
        if self.metadata_id and self.origin_fingerprint:
            return 'show:meta:{}:{}'.format(self.origin_fingerprint, self.metadata_id)
        return None

    @property
    def canonical_key(self):
        if self.kind == 'movie':
            if self.imdb_id:
                return 'movie:imdb:{}'.format(self.imdb_id)
            if self.tmdb_id:
                return 'movie:{}'.format(_namespaced_tmdb(self.tmdb_id))
            if self.metadata_id and self.origin_fingerprint:
                return 'movie:meta:{}:{}'.format(self.origin_fingerprint, self.metadata_id)
            return None
        show_key = self.show_key
        if not show_key or self.season is None or self.episode is None:
            return None
        return 'episode:{}:{}:{}'.format(show_key, self.season, self.episode)

    @property
    def is_identifiable(self):
        return bool(self.canonical_key)


def media_ref_from_route(params, origin_fingerprint=None):
    """Build history identity from a Kodi route without importing Kodi models."""
    params = params or {}
    content_type = params.get('content_type') or params.get('media_type') or 'movie'
    episode = content_type in ('episode', 'series', 'show', 'tvshow') and params.get('season') not in (None, '')
    if episode:
        return HistoryMediaRef(
            'episode', imdb_id=params.get('episode_imdb_id'), tmdb_id=params.get('episode_tmdb_id'),
            show_imdb_id=params.get('show_imdb_id') or params.get('imdb_id'),
            show_tmdb_id=params.get('show_tmdb_id') or params.get('tmdb_id'),
            season=params.get('season'), episode=params.get('episode'),
            metadata_id=params.get('meta_id') or params.get('metadata_id'),
            origin_fingerprint=params.get('origin_fingerprint') or origin_fingerprint,
            title=params.get('title', ''), show_title=params.get('show_title'),
        )
    return HistoryMediaRef(
        'movie', imdb_id=params.get('imdb_id'), tmdb_id=params.get('tmdb_id'),
        metadata_id=params.get('meta_id') or params.get('metadata_id'),
        origin_fingerprint=params.get('origin_fingerprint') or origin_fingerprint,
        title=params.get('title', ''),
    )


@dataclass(frozen=True)
class ResumePoint:
    position: float
    duration: float = 0
    percent_played: float = 0


@dataclass(frozen=True)
class HistoryState:
    available: bool = False
    watched: bool = False
    play_count: int = 0
    percent_played: float = 0
    resume_time: float = 0


class PlaybackEventType(str, Enum):
    START = 'start'
    PROGRESS = 'progress'
    PAUSE = 'pause'
    RESUME = 'resume'
    STOP = 'stop'
    ENDED = 'ended'
    SEEK = 'seek'


@dataclass(frozen=True)
class PlaybackEvent:
    event_type: PlaybackEventType
    media: HistoryMediaRef
    position: float = 0
    duration: float = 0
    percent_played: float = 0
    timestamp: Optional[int] = None


@dataclass(frozen=True)
class NextUpEntry:
    media: HistoryMediaRef
    state: HistoryState = field(default_factory=HistoryState)
    air_date: Optional[str] = None


@dataclass(frozen=True)
class ProviderCapabilities:
    progress: bool = True
    next_up: bool = True
    synchronization: bool = False


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: str
    enabled: bool
    available: bool
    authenticated: bool = True
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    message: str = ''


class ProviderResultCode(str, Enum):
    SUCCESS = 'success'
    DISABLED = 'disabled'
    AUTHENTICATION_UNAVAILABLE = 'authentication_unavailable'
    TEMPORARY_FAILURE = 'temporary_failure'
    UNSUPPORTED = 'unsupported'


@dataclass(frozen=True)
class ProviderResult:
    code: ProviderResultCode
    provider_id: str
    message: str = ''
    fallback_provider_id: Optional[str] = None

    @property
    def succeeded(self):
        return self.code == ProviderResultCode.SUCCESS

    @property
    def allows_fallback(self):
        return self.code in (
            ProviderResultCode.DISABLED,
            ProviderResultCode.AUTHENTICATION_UNAVAILABLE,
            ProviderResultCode.TEMPORARY_FAILURE,
        )
