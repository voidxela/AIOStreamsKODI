import json
import os
import sys
import unittest

from kodi_stubs import install


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, 'plugin.video.aiostreams'))


class NativeFavoriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install()
        from resources.lib.actions import browse
        from resources.lib.native_favorites import (
            FavoritesDisplayPoller, list_aiostreams_favorites, parse_favorite,
        )

        cls.browse = browse
        cls.FavoritesDisplayPoller = FavoritesDisplayPoller
        cls.list_aiostreams_favorites = staticmethod(list_aiostreams_favorites)
        cls.parse_favorite = staticmethod(parse_favorite)
        cls.xbmcgui = browse.xbmcgui
        cls.xbmcplugin = browse.xbmcplugin

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop('resources.lib.actions.browse', None)
        actions = sys.modules.get('resources.lib.actions')
        if actions and hasattr(actions, 'browse'):
            delattr(actions, 'browse')

    def setUp(self):
        self.directory_items = []
        self.xbmcplugin.setPluginCategory = lambda *_args: None
        self.xbmcplugin.setContent = lambda *_args: None
        self.xbmcplugin.addDirectoryItem = lambda *args: self.directory_items.append(args)
        self.xbmcplugin.endOfDirectory = lambda *_args, **_kwargs: None

    def dependencies(self, records):
        return self.browse.BrowseDependencies(
            handle=1,
            has_modules=False,
            filters=None,
            get_url=lambda **_params: '',
            get_manifest=lambda: None,
            get_catalog=lambda *_args: None,
            get_meta=lambda *_args: None,
            fetch_metadata_parallel=lambda *_args: {},
            get_cached_clearlogo_path=lambda *_args: None,
            ensure_clearlogo_cached=lambda *_args: None,
            format_season_title=lambda *_args: '',
            format_episode_title=lambda *_args: '',
            apply_media_identity=lambda *_args: None,
            create_listitem=lambda *_args: None,
            get_native_favorites=lambda: records,
        )

    def test_parser_accepts_only_movie_and_show_targets(self):
        series = self.parse_favorite({
            'type': 'window', 'title': 'Yellowstone', 'thumbnail': 'show-thumb',
            'windowparameter': 'plugin://plugin.video.aiostreams/?action=show_seasons&content_type=series&meta_id=series%3A1&imdb_id=tt4236770',
        })
        movie = self.parse_favorite({
            'type': 'media', 'title': 'Arrival', 'thumbnail': 'movie-thumb',
            'path': 'plugin://plugin.video.aiostreams/?action=play&content_type=movie&meta_id=movie%3A1&media_id=stream%3A1&imdb_id=tt2543164',
        })

        self.assertEqual('series', series.content_type)
        self.assertTrue(series.is_folder)
        self.assertEqual(
            'plugin://plugin.video.aiostreams/?action=show_seasons&content_type=series&meta_id=series%3A1&imdb_id=tt4236770',
            series.target,
        )
        self.assertEqual('movie', movie.content_type)
        self.assertFalse(movie.is_folder)
        self.assertIsNone(self.parse_favorite({
            'type': 'media',
            'path': 'plugin://plugin.video.aiostreams/?action=browse_catalog&catalog_id=popular',
        }))
        self.assertIsNone(self.parse_favorite({
            'type': 'media',
            'path': 'plugin://plugin.video.aiostreams/?action=search&content_type=both&query=Arrival',
        }))
        self.assertIsNone(self.parse_favorite({
            'type': 'media',
            'path': 'plugin://plugin.video.other/?action=play&content_type=movie&meta_id=1',
        }))

    def test_json_rpc_records_keep_kodis_title_thumbnail_and_exact_target(self):
        target = 'plugin://plugin.video.aiostreams/?action=play&content_type=movie&meta_id=movie%3A1&media_id=stream%3A1&imdb_id=tt2543164'
        requests = []

        def execute_jsonrpc(request):
            requests.append(json.loads(request))
            return json.dumps({'result': {'favourites': [{
                'type': 'media', 'title': 'Arrival', 'thumbnail': 'thumb', 'path': target,
            }]}})

        favorites = self.list_aiostreams_favorites(execute_jsonrpc)

        self.assertEqual('Favourites.GetFavourites', requests[0]['method'])
        self.assertEqual(['path', 'windowparameter', 'thumbnail'], requests[0]['params']['properties'])
        self.assertEqual(target, favorites[0].target)
        self.assertEqual('Arrival', favorites[0].title)
        self.assertEqual('thumb', favorites[0].thumbnail)

    def test_favorites_view_renders_native_data_without_custom_context_actions(self):
        target = 'plugin://plugin.video.aiostreams/?action=show_seasons&content_type=series&meta_id=series%3A1'
        favorite = self.parse_favorite({
            'type': 'media', 'title': 'Yellowstone', 'thumbnail': 'show-thumb', 'path': target,
        })

        self.browse.favorites({}, self.dependencies([favorite]))

        _handle, rendered_target, list_item, is_folder = self.directory_items[0]
        self.assertEqual(target, rendered_target)
        self.assertEqual('Yellowstone', list_item.label)
        self.assertEqual('show-thumb', list_item.art['poster'])
        self.assertEqual([], list_item.context_menu)
        self.assertTrue(is_folder)

    def test_display_poller_refreshes_only_after_native_favorites_change(self):
        now = [0]
        path = ['plugin://plugin.video.aiostreams/?action=favorites']
        entries = [self.parse_favorite({
            'type': 'media', 'title': 'Arrival',
            'path': 'plugin://plugin.video.aiostreams/?action=play&content_type=movie&meta_id=movie%3A1',
        })]
        refreshed = []
        poller = self.FavoritesDisplayPoller(
            current_path=lambda: path[0], get_favorites=lambda: entries,
            refresh=lambda: refreshed.append(True), clock=lambda: now[0],
        )

        self.assertFalse(poller.poll())
        now[0] = 9
        self.assertFalse(poller.poll())
        entries.clear()
        now[0] = 10
        self.assertTrue(poller.poll())
        self.assertEqual([True], refreshed)
        now[0] = 20
        self.assertFalse(poller.poll())
        path[0] = 'plugin://plugin.video.aiostreams/?action=index'
        self.assertFalse(poller.poll())


if __name__ == '__main__':
    unittest.main()
