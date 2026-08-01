import os
import sys
import threading
import unittest

from kodi_stubs import install


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, 'plugin.video.aiostreams'))


class Window:
    def __init__(self, _window_id):
        self.values = {}

    def setProperty(self, key, value):
        self.values[key] = value

    def clearProperty(self, key):
        self.values.pop(key, None)


class Dialog:
    response = ''
    confirmed = True

    def input(self, *_args, **_kwargs):
        return self.response

    def yesno(self, *_args, **_kwargs):
        return self.confirmed


class Progress:
    cancelled = False
    instances = []

    def __init__(self):
        self.closed = False
        Progress.instances.append(self)

    def create(self, *_args):
        return None

    def update(self, *_args):
        return None

    def iscanceled(self):
        return self.cancelled

    def close(self):
        self.closed = True


class State:
    def __init__(self, scope='all', searches=None):
        self.scope = scope
        self.searches = searches or []
        self.recorded = []
        self.removed = []
        self.cleared = False

    def get_last_search_scope(self):
        return self.scope

    def set_last_search_scope(self, scope):
        self.scope = scope

    def record_search(self, query, scope):
        self.recorded.append((query, scope))

    def list_searches(self):
        return self.searches

    def remove_search(self, query, scope):
        self.removed.append((query, scope))
        return True

    def clear_searches(self):
        self.cleared = True


class SearchActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install()
        from resources.lib.actions import search
        # Other contract tests import the add-on first, so configure the Kodi
        # module objects retained by this action module rather than replacing
        # sys.modules with a second set of stubs.
        cls.search = search
        cls.xbmc = search.xbmc
        cls.xbmcplugin = search.xbmcplugin
        xbmcgui = search.xbmcgui
        xbmcgui.Window = Window
        xbmcgui.Dialog = Dialog
        xbmcgui.DialogProgress = Progress
        xbmcgui.INPUT_ALPHANUM = 0

    def setUp(self):
        self.directory_items = []
        self.end_calls = []
        self.executed = []
        self.xbmcplugin.setPluginCategory = lambda *_args: None
        self.xbmcplugin.setContent = lambda *_args: None
        self.xbmcplugin.addDirectoryItem = lambda *args: self.directory_items.append(args)
        self.xbmcplugin.endOfDirectory = lambda *args, **kwargs: self.end_calls.append((args, kwargs))
        self.xbmc.executebuiltin = self.executed.append
        Dialog.response = ''
        Dialog.confirmed = True
        Progress.cancelled = False
        Progress.instances = []
        self.search._search_result_cache.clear()

    def dependencies(self, state, search_catalog):
        return self.search.SearchDependencies(
            handle=1,
            has_modules=False,
            filters=None,
            search_catalog=search_catalog,
            get_url=lambda **params: 'plugin://test/?{}'.format(
                '&'.join('{}={}'.format(key, value) for key, value in sorted(params.items()))
            ),
            create_listitem=lambda meta, *_args: sys.modules['xbmcgui'].ListItem(meta.get('name', 'Result')),
            origin_fingerprint='configuration-a',
            user_state=state,
        )

    def test_empty_scope_defaults_to_combined_search_and_records_a_submitted_search(self):
        state = State(scope='shows')
        Dialog.response = 'The Last of Us'
        calls = []
        dependencies = self.dependencies(
            state,
            lambda query, content_type, skip=0: (
                calls.append((query, content_type, skip)) or {'metas': []}
            ),
        )

        self.search._search({}, dependencies)

        self.assertEqual(
            {('The Last of Us', 'movie', 0), ('The Last of Us', 'series', 0)},
            set(calls),
        )
        self.assertEqual([('The Last of Us', 'all')], state.recorded)
        self.assertEqual('all', state.scope)

    def test_cancelled_input_does_not_record_or_search(self):
        state = State()
        dependencies = self.dependencies(state, lambda *_args, **_kwargs: self.fail('must not search'))

        self.search._search({}, dependencies)

        self.assertEqual([], state.recorded)
        self.assertEqual([], state.searches)

    def test_combined_search_runs_both_requests_and_view_all_uses_its_cached_result(self):
        state = State()
        calls = []
        barrier = threading.Barrier(2)

        def search_catalog(query, content_type, skip=0):
            calls.append((query, content_type, skip, threading.get_ident()))
            barrier.wait(timeout=2)
            count = 11 if content_type == 'movie' else 1
            return {'metas': [{'name': '{} {}'.format(content_type, index), 'type': content_type} for index in range(count)]}

        dependencies = self.dependencies(state, search_catalog)
        self.search._search({'content_type': 'both', 'query': 'Dune'}, dependencies)
        self.assertEqual({'movie', 'series'}, {call[1] for call in calls})
        self.assertEqual(2, len({call[3] for call in calls}))
        self.assertIn('movie 0', [item[2].label for item in self.directory_items])
        self.assertTrue(any('record_history=false' in item[1] for item in self.directory_items))

        self.directory_items.clear()
        self.search._search(
            {'content_type': 'movie', 'query': 'Dune', 'record_history': 'false'}, dependencies,
        )
        self.assertEqual(2, len(calls))
        self.assertEqual([('Dune', 'all')], state.recorded)

    def test_recent_searches_render_rerun_remove_and_clear_actions(self):
        state = State(searches=[{'query': 'Arrival', 'content_type': 'movies'}])
        dependencies = self.dependencies(state, lambda *_args, **_kwargs: {'metas': []})

        self.search.recent_searches({}, dependencies)

        list_item = self.directory_items[0][2]
        self.assertEqual('Arrival [COLOR gray](Movies)[/COLOR]', list_item.label)
        self.assertIn('content_type=movie', self.directory_items[0][1])
        self.assertEqual(2, len(list_item.context_menu))
        self.search.remove_recent_search({'query': 'Arrival', 'content_type': 'movies'}, dependencies)
        self.search.clear_recent_searches({}, dependencies)
        self.assertEqual([('Arrival', 'movies')], state.removed)
        self.assertTrue(state.cleared)
        self.assertEqual(['Container.Refresh', 'Container.Refresh'], self.executed)

    def test_cancelled_combined_search_closes_its_progress_dialog(self):
        state = State()
        Progress.cancelled = True
        dependencies = self.dependencies(state, lambda *_args, **_kwargs: {'metas': []})

        self.search._search({'content_type': 'both', 'query': 'Dune'}, dependencies)

        self.assertTrue(Progress.instances[-1].closed)
        self.assertEqual(False, self.end_calls[-1][1]['succeeded'])


if __name__ == '__main__':
    unittest.main()
