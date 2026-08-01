"""Search actions, recent-query UI, and bounded combined searching."""
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
import threading
import time

import xbmc
import xbmcgui
import xbmcplugin

from ..items import media_action_params
from ..media import MediaRef


@dataclass(frozen=True)
class SearchDependencies:
    """The narrow add-on services required to render search results."""

    handle: int
    has_modules: bool
    filters: object
    search_catalog: object
    get_url: object
    create_listitem: object
    origin_fingerprint: object = None
    user_state: object = None


SEARCH_CACHE_TTL_SECONDS = 60
SEARCH_CACHE_LIMIT = 20
_search_result_cache = {}
_search_cache_lock = threading.Lock()


def _content_type_for_scope(scope):
    return {'all': 'both', 'movies': 'movie', 'shows': 'series'}.get(scope, 'both')


def _scope_for_content_type(content_type):
    return {
        'all': 'all', 'both': 'all',
        'movie': 'movies', 'movies': 'movies',
        'series': 'shows', 'show': 'shows', 'shows': 'shows',
    }.get((content_type or '').lower(), 'all')


def _normalized_content_type(content_type, dependencies):
    if not content_type:
        return 'both'
    return _content_type_for_scope(_scope_for_content_type(content_type))


def _cache_key(query, content_type, skip, dependencies):
    return (
        dependencies.origin_fingerprint or '',
        ' '.join((query or '').split()).casefold(), content_type, int(skip),
    )


def _cached_search_results(query, content_type, skip, dependencies):
    key = _cache_key(query, content_type, skip, dependencies)
    with _search_cache_lock:
        cached = _search_result_cache.get(key)
        if not cached:
            return None
        expires_at, results = cached
        if expires_at <= time.monotonic():
            del _search_result_cache[key]
            return None
        return results


def _cache_search_results(query, content_type, skip, results, dependencies):
    if not isinstance(results, dict):
        return results
    key = _cache_key(query, content_type, skip, dependencies)
    with _search_cache_lock:
        _search_result_cache[key] = (time.monotonic() + SEARCH_CACHE_TTL_SECONDS, results)
        while len(_search_result_cache) > SEARCH_CACHE_LIMIT:
            oldest_key = min(_search_result_cache, key=lambda item: _search_result_cache[item][0])
            del _search_result_cache[oldest_key]
    return results


def _get_search_results(query, content_type, skip, dependencies):
    cached = _cached_search_results(query, content_type, skip, dependencies)
    if cached is not None:
        return cached
    return _cache_search_results(
        query, content_type, skip,
        dependencies.search_catalog(query, content_type, skip=skip), dependencies,
    )


def _should_record_history(params, skip):
    return skip == 0 and str(params.get('record_history', 'true')).lower() not in ('0', 'false', 'no')


def _remember_search(query, content_type, dependencies):
    state = dependencies.user_state
    if not state:
        return
    scope = _scope_for_content_type(content_type)
    try:
        state.set_last_search_scope(scope)
        state.record_search(query, scope)
    except Exception as error:
        xbmc.log('[AIOStreams] Could not save search history: {}'.format(type(error).__name__), xbmc.LOGWARNING)


def _set_background_suppression(active):
    """Pause background work while a foreground search is loading."""
    try:
        window = xbmcgui.Window(10000)
        if active:
            window.setProperty('AIOStreams.InternalSearchActive', 'true')
            xbmc.executebuiltin('Skin.ClearString(WidgetReloadToken)')
            from service import get_task_queue
            get_task_queue().clear()
            xbmc.log('[AIOStreams] Internal Search started', xbmc.LOGINFO)
        else:
            window.clearProperty('AIOStreams.InternalSearchActive')
            xbmc.executebuiltin('Skin.ClearString(WidgetReloadToken)')
            xbmc.log('[AIOStreams] Internal Search finished', xbmc.LOGDEBUG)
    except Exception as error:
        xbmc.log(f'[AIOStreams] Error managing background tasks: {error}', xbmc.LOGDEBUG)


def _filter_items(items, dependencies):
    if dependencies.has_modules and dependencies.filters:
        return dependencies.filters.filter_items(items)
    return items


def search(params, dependencies):
    """Render one movie, show, video, or combined result set."""
    _set_background_suppression(True)
    try:
        return _search(params, dependencies)
    finally:
        _set_background_suppression(False)


def _search(params, dependencies):
    content_type = _normalized_content_type(params.get('content_type'), dependencies)
    query = params.get('query', '').strip()
    try:
        skip = int(params.get('skip', 0))
    except (TypeError, ValueError):
        skip = 0
    window = xbmcgui.Window(10000)

    if not query:
        query = xbmcgui.Dialog().input('Search', type=xbmcgui.INPUT_ALPHANUM)
        query = (query or '').strip()
        if not query:
            xbmcplugin.endOfDirectory(dependencies.handle, succeeded=False)
            return None

    if _should_record_history(params, skip):
        _remember_search(query, content_type, dependencies)

    if content_type == 'both' and skip == 0:
        return search_all_results(query, dependencies)

    xbmcplugin.setPluginCategory(dependencies.handle, f'Search {content_type.title()}: {query}')
    xbmcplugin.setContent(
        dependencies.handle, 'movies' if content_type == 'movie' else 'tvshows'
    )
    progress = xbmcgui.DialogProgress()
    content_label = 'TV shows' if content_type == 'series' else f'{content_type}s'
    progress.create('AIOStreams', f'Searching {content_label}...')
    try:
        results = _get_search_results(query, content_type, skip, dependencies)
    finally:
        progress.close()

    if not results or not results.get('metas'):
        _set_result_count(window, content_type, 0)
        xbmc.log(f'[AIOStreams] Search returned no results for "{query}"', xbmc.LOGINFO)
        xbmcplugin.endOfDirectory(dependencies.handle, succeeded=True)
        return None

    _set_result_count(window, content_type, len(results['metas']))
    items = _filter_items(results['metas'], dependencies)
    for meta in items:
        _add_result(meta, content_type, dependencies)

    if len(results['metas']) >= 20:
        next_skip = skip + 20
        list_item = xbmcgui.ListItem(label='[COLOR yellow]» Load More...[/COLOR]')
        url = dependencies.get_url(
            action='search', content_type=content_type, query=query, skip=next_skip,
            record_history='false',
        )
        xbmcplugin.addDirectoryItem(dependencies.handle, url, list_item, True)
    xbmcplugin.endOfDirectory(dependencies.handle)
    return None


def _set_result_count(window, content_type, count):
    if content_type == 'movie':
        window.setProperty('GlobalSearch.MoviesCount', str(count))
    elif content_type in ('tvshows', 'series'):
        window.setProperty('GlobalSearch.SeriesCount', str(count))
    elif content_type in ('video', 'youtube') or 'youtube' in str(content_type):
        window.setProperty('GlobalSearch.YoutubeCount', str(count))


def _add_result(meta, content_type, dependencies):
    item_type = 'video' if content_type in ('video', 'youtube') else meta.get('type', content_type)
    media = MediaRef.from_meta(meta, item_type, dependencies.origin_fingerprint)
    item_type = media.content_type
    if item_type == 'series':
        url = dependencies.get_url(
            action='show_seasons', **media_action_params('show_seasons', media)
        )
        is_folder = True
    elif content_type in ('video', 'youtube') or 'youtube' in str(item_type):
        item_url = meta.get('url', '')
        item_name = meta.get('name', '')
        is_youtube_folder = (
            '/channel/' in item_url or '/playlist/' in item_url or
            'Channels' in item_name or 'Playlists' in item_name or
            meta.get('mediatype') in ('channel', 'playlist')
        )
        if is_youtube_folder:
            if not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
                return
            url = dependencies.get_url(action='open_youtube_folder', url=item_url or meta.get('id', ''))
            is_folder = False
        else:
            url = dependencies.get_url(
                action='play', **media_action_params('play', media, clearlogo=meta.get('logo', ''))
            )
            is_folder = False
    else:
        url = dependencies.get_url(
            action='play', **media_action_params('play', media, clearlogo=meta.get('logo', ''))
        )
        is_folder = False

    list_item = dependencies.create_listitem(meta, item_type, url)
    if not is_folder:
        list_item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(dependencies.handle, url, list_item, is_folder)


def _unique_results(metas, content_type):
    """Preserve backend order while dropping duplicate media in one scope."""
    unique = []
    seen = set()
    for meta in metas:
        if not isinstance(meta, dict):
            continue
        identifier = (
            meta.get('metadata_id') or meta.get('meta_id') or meta.get('id') or
            meta.get('imdb_id') or meta.get('imdbId') or
            meta.get('tmdb_id') or meta.get('tmdbId')
        )
        if not identifier:
            identifier = (meta.get('name') or meta.get('title') or '', meta.get('year') or '')
        key = (content_type, str(identifier))
        if key not in seen:
            seen.add(key)
            unique.append(meta)
    return unique


def search_all_results(query, dependencies):
    """Render combined movie and show results in a single directory."""
    xbmcplugin.setPluginCategory(dependencies.handle, f'Search: {query}')
    xbmcplugin.setContent(dependencies.handle, 'videos')
    progress = xbmcgui.DialogProgress()
    progress.create('AIOStreams', 'Searching movies and TV shows...')
    results = {}
    failures = {}
    cancelled = False
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='AIOStreamsSearch')
    try:
        progress.update(25, 'Searching movies and TV shows...')
        futures = {
            executor.submit(_get_search_results, query, 'movie', 0, dependencies): 'movie',
            executor.submit(_get_search_results, query, 'series', 0, dependencies): 'series',
        }
        pending = set(futures)
        while pending:
            if _search_cancelled(progress):
                cancelled = True
                for future in pending:
                    future.cancel()
                break
            done, pending = wait(pending, timeout=0.1)
            if _search_cancelled(progress):
                cancelled = True
                for future in pending:
                    future.cancel()
                break
            for future in done:
                content_type = futures[future]
                try:
                    results[content_type] = future.result()
                except Exception as error:
                    failures[content_type] = error
                    xbmc.log(
                        '[AIOStreams] {} search failed during combined search: {}'.format(
                            content_type, type(error).__name__,
                        ),
                        xbmc.LOGWARNING,
                    )
            if 'movie' in results or 'movie' in failures:
                progress.update(60, 'Searching TV shows...')
    finally:
        progress.close()
        # Workers never touch Kodi UI.  Close the dialog before joining them so
        # cancellation cannot leave a modal progress window on screen, then
        # join every worker to avoid orphaned executor threads.
        executor.shutdown(wait=True)

    if cancelled:
        xbmcplugin.endOfDirectory(dependencies.handle, succeeded=False)
        return None

    if len(failures) == 2:
        xbmcgui.Dialog().notification(
            'AIOStreams', 'Movie and TV show searches failed', xbmcgui.NOTIFICATION_ERROR,
        )
        xbmcplugin.endOfDirectory(dependencies.handle, succeeded=False)
        return None

    movies = _filter_items(
        _unique_results((results.get('movie') or {}).get('metas', []), 'movie'), dependencies,
    )
    for meta in movies[:10]:
        _add_result(meta, 'movie', dependencies)
    if len(movies) > 10:
        list_item = xbmcgui.ListItem(
            label=f'[COLOR yellow]   » View All Movies ({len(movies)} results)[/COLOR]'
        )
        url = dependencies.get_url(
            action='search', content_type='movie', query=query, record_history='false'
        )
        xbmcplugin.addDirectoryItem(dependencies.handle, url, list_item, True)

    shows = _filter_items(
        _unique_results((results.get('series') or {}).get('metas', []), 'series'), dependencies,
    )
    for meta in shows[:10]:
        _add_result(meta, 'series', dependencies)
    if len(shows) > 10:
        list_item = xbmcgui.ListItem(
            label=f'[COLOR yellow]   » View All TV Shows ({len(shows)} results)[/COLOR]'
        )
        url = dependencies.get_url(
            action='search_tab', content_type='series', query=query, record_history='false'
        )
        xbmcplugin.addDirectoryItem(dependencies.handle, url, list_item, True)

    if not movies and not shows:
        list_item = xbmcgui.ListItem(label=f'[COLOR red]No results found for "{query}"[/COLOR]')
        xbmcplugin.addDirectoryItem(dependencies.handle, '', list_item, False)
    xbmcplugin.endOfDirectory(dependencies.handle)
    return None


def _search_cancelled(progress):
    try:
        return progress.iscanceled()
    except AttributeError:
        return False


def recent_searches(params, dependencies):
    """List persisted searches with actions to rerun or remove them."""
    xbmcplugin.setPluginCategory(dependencies.handle, 'Recent Searches')
    xbmcplugin.setContent(dependencies.handle, 'files')
    try:
        searches = dependencies.user_state.list_searches() if dependencies.user_state else []
    except Exception as error:
        xbmc.log('[AIOStreams] Could not read search history: {}'.format(type(error).__name__), xbmc.LOGWARNING)
        searches = []

    for entry in searches:
        scope = entry['content_type']
        query = entry['query']
        list_item = xbmcgui.ListItem(label='{} [COLOR gray]({})[/COLOR]'.format(query, scope.title()))
        list_item.getVideoInfoTag().setTitle(query)
        url = dependencies.get_url(
            action='search', content_type=_content_type_for_scope(scope), query=query,
        )
        remove_url = dependencies.get_url(
            action='remove_recent_search', query=query, content_type=scope,
        )
        list_item.addContextMenuItems([
            ('Remove from Recent Searches', 'RunPlugin({})'.format(remove_url)),
            ('Clear Recent Searches', 'RunPlugin({})'.format(
                dependencies.get_url(action='clear_recent_searches')
            )),
        ])
        xbmcplugin.addDirectoryItem(dependencies.handle, url, list_item, True)

    if not searches:
        xbmcplugin.addDirectoryItem(
            dependencies.handle, '', xbmcgui.ListItem(label='[COLOR gray]No recent searches[/COLOR]'), False,
        )
    xbmcplugin.endOfDirectory(dependencies.handle)
    return None


def remove_recent_search(params, dependencies):
    """Remove one recent query then refresh the open history directory."""
    try:
        if dependencies.user_state:
            dependencies.user_state.remove_search(
                params.get('query', ''), params.get('content_type', 'all'),
            )
    except Exception as error:
        xbmc.log('[AIOStreams] Could not remove search history entry: {}'.format(type(error).__name__), xbmc.LOGWARNING)
    xbmc.executebuiltin('Container.Refresh')
    return None


def clear_recent_searches(params, dependencies):
    """Confirm and clear only search history, never favorites or cache data."""
    if not xbmcgui.Dialog().yesno(
        'Clear Recent Searches', 'Remove all saved search queries?', 'This does not remove favorites.',
    ):
        return None
    try:
        if dependencies.user_state:
            dependencies.user_state.clear_searches()
    except Exception as error:
        xbmc.log('[AIOStreams] Could not clear search history: {}'.format(type(error).__name__), xbmc.LOGWARNING)
        return None
    xbmc.executebuiltin('Container.Refresh')
    return None
