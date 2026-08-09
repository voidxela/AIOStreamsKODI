"""Provider-neutral Kodi actions for watched state, progress and Next Up."""
from dataclasses import dataclass

import xbmc
import xbmcgui
import xbmcplugin

from ..history import HistoryMediaRef, media_ref_from_route
from ..items import media_action_params
from ..media import MediaRef


@dataclass(frozen=True)
class HistoryDependencies:
    handle: int
    get_url: object
    history_manager: object
    get_meta: object = None
    create_listitem: object = None
    origin_fingerprint: object = None
    addon: object = None


def _media(params, dependencies):
    return media_ref_from_route(params, dependencies.origin_fingerprint)


def _show(params, dependencies):
    return HistoryMediaRef(
        'episode', show_imdb_id=params.get('show_imdb_id') or params.get('imdb_id'),
        show_tmdb_id=params.get('show_tmdb_id') or params.get('tmdb_id'),
        metadata_id=params.get('meta_id'), origin_fingerprint=params.get('origin_fingerprint') or dependencies.origin_fingerprint,
        show_title=params.get('title') or params.get('show_title'),
    )


def _refresh():
    xbmc.executebuiltin('Container.Refresh')


def _mutate(params, dependencies, watched=None, hidden=None, clear=False):
    media = _show(params, dependencies) if hidden is not None else _media(params, dependencies)
    if clear:
        result = dependencies.history_manager.clear_progress(media)
    elif hidden is not None:
        result = dependencies.history_manager.set_next_up_hidden(media, hidden)
    else:
        result = dependencies.history_manager.mark_watched(media, watched)
    if result.succeeded:
        _refresh()
    elif result.code.value != 'disabled':
        xbmcgui.Dialog().notification('AIOStreams', 'History update unavailable', xbmcgui.NOTIFICATION_WARNING)
    return result


def mark_watched(params, dependencies):
    return _mutate(params, dependencies, watched=True)


def mark_unwatched(params, dependencies):
    return _mutate(params, dependencies, watched=False)


def clear_progress(params, dependencies):
    return _mutate(params, dependencies, clear=True)


def hide_from_next_up(params, dependencies):
    return _mutate(params, dependencies, hidden=True)


def unhide_from_next_up(params, dependencies):
    return _mutate(params, dependencies, hidden=False)


def next_up(params, dependencies):
    """Render provider entries; enrichment remains at the Kodi action boundary."""
    xbmcplugin.setPluginCategory(dependencies.handle, 'Next Up')
    xbmcplugin.setContent(dependencies.handle, 'episodes')
    entries = dependencies.history_manager.list_next_up()
    for entry in entries:
        media = entry.media
        show_meta = {}
        if dependencies.get_meta and (media.show_imdb_id or media.metadata_id):
            try:
                response = dependencies.get_meta('series', media.show_imdb_id or media.metadata_id) or {}
                show_meta = response.get('meta') or {}
            except Exception:
                show_meta = {}
        show_ref = MediaRef.from_meta(
            show_meta or {'id': media.metadata_id or media.show_imdb_id, 'imdb_id': media.show_imdb_id,
                          'tmdb_id': media.show_tmdb_id, 'name': media.show_title or 'Unknown'},
            'series', dependencies.origin_fingerprint,
        )
        episode_ref = MediaRef.episode(show_ref, {
            'id': media.metadata_id or media.imdb_id, 'imdb_id': media.imdb_id,
            'tmdb_id': media.tmdb_id, 'title': media.title,
        }, media.season, media.episode, dependencies.origin_fingerprint)
        label = '{} S{:02d}E{:02d}'.format(media.show_title or show_ref.title, media.season or 0, media.episode or 0)
        url = dependencies.get_url(
            action='play', **media_action_params('play', show_ref, media_id=episode_ref.playback_id,
                                                   season=media.season, episode=media.episode,
                                                   title=label),
        )
        meta = dict(show_meta)
        meta.update({'id': episode_ref.metadata_id, 'imdb_id': media.imdb_id, 'name': label,
                     'description': show_meta.get('description', ''), 'released': entry.air_date or ''})
        list_item = dependencies.create_listitem(meta, 'episode', url) if dependencies.create_listitem else xbmcgui.ListItem(label=label)
        list_item.setProperty('IsPlayable', 'true')
        list_item.setProperty('IsNextUpEpisode', 'true')
        xbmcplugin.addDirectoryItem(dependencies.handle, url, list_item, False)
    if not entries:
        xbmcgui.Dialog().notification('AIOStreams', 'No shows in progress', xbmcgui.NOTIFICATION_INFO)
    xbmcplugin.endOfDirectory(dependencies.handle)


def clear_local_history(params, dependencies):
    if xbmcgui.Dialog().yesno('AIOStreams', 'Clear all local watched history and resume points?'):
        result = dependencies.history_manager.clear_local_history()
        if result.succeeded:
            _refresh()
    return None


def import_legacy_trakt_history(params, dependencies):
    if not xbmcgui.Dialog().yesno(
            'AIOStreams',
            'Import watched state and resume points from the cached legacy Trakt database?',
            'Watchlists, collections, and ratings will not be copied.'):
        return None
    result = dependencies.history_manager.import_legacy_trakt_history()
    if result.succeeded:
        xbmcgui.Dialog().notification('AIOStreams', 'Cached Trakt history imported', xbmcgui.NOTIFICATION_INFO)
        _refresh()
    else:
        xbmcgui.Dialog().notification('AIOStreams', 'Unable to import cached Trakt history', xbmcgui.NOTIFICATION_WARNING)
    return result


def configure_provider(params, dependencies):
    """Open the active provider's own configuration wizard."""
    result = dependencies.history_manager.configure(dependencies.addon)
    if result.succeeded:
        xbmcgui.Dialog().notification('AIOStreams', 'History provider configuration updated', xbmcgui.NOTIFICATION_INFO)
    elif result.code.value != 'disabled':
        xbmcgui.Dialog().notification('AIOStreams', 'History provider configuration unavailable', xbmcgui.NOTIFICATION_WARNING)
    return result


def select_provider(params, dependencies):
    """Persist the provider choice, then reload Kodi's cached settings dialog."""
    providers = (
        ('Local History', 'local'),
        ('Legacy Trakt History', 'trakt_legacy'),
        ('Disabled', 'none'),
    )
    current_id = dependencies.history_manager.primary.provider_id
    preselect = next((index for index, (_label, provider_id) in enumerate(providers)
                      if provider_id == current_id), 0)
    selected = xbmcgui.Dialog().select('Select History Provider', [label for label, _provider_id in providers], preselect=preselect)
    if selected < 0:
        return None

    # Add-on settings are cached while their dialog is open. Closing it before
    # setSetting prevents the stale in-memory selection from overwriting the
    # provider choice as the RunPlugin action returns.
    xbmc.executebuiltin('Dialog.Close(addonsettings)')
    xbmc.sleep(200)
    result = dependencies.history_manager.select_provider(dependencies.addon, providers[selected][1])
    if result.succeeded:
        xbmcgui.Dialog().notification('AIOStreams', 'History provider set to {}'.format(providers[selected][0]),
                                      xbmcgui.NOTIFICATION_INFO)
        # Reopen settings from disk so the provider label and its named status
        # rows visibly switch without requiring a Kodi restart.
        xbmc.executebuiltin('Addon.OpenSettings(plugin.video.aiostreams)')
    return result
