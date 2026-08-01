import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, 'plugin.video.aiostreams'))

from resources.lib.user_state import UserState, UserStateError  # noqa: E402


class Clock:
    def __init__(self):
        self.value = 1000

    def __call__(self):
        self.value += 1
        return self.value


class UserStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temporary_directory.name, 'user_state.db')
        self.clock = Clock()
        self.state = UserState(self.database_path, clock=self.clock)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_schema_migrates_from_an_unversioned_database(self):
        with sqlite3.connect(self.database_path) as connection:
            connection.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)')
            connection.execute('INSERT INTO schema_version(version) VALUES (0)')

        self.assertTrue(self.state.record_search('Arrival', 'movies'))
        with sqlite3.connect(self.database_path) as connection:
            version = connection.execute('SELECT version FROM schema_version').fetchone()[0]
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertEqual(3, version)
        self.assertTrue({'search_history'}.issubset(tables))
        self.assertNotIn('preferences', tables)
        self.assertNotIn('favorites', tables)

    def test_legacy_favorites_table_is_removed_without_touching_searches_or_preferences(self):
        with sqlite3.connect(self.database_path) as connection:
            connection.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)')
            connection.execute('INSERT INTO schema_version(version) VALUES (2)')
            connection.execute('CREATE TABLE favorites (favorite_key TEXT PRIMARY KEY)')
            connection.execute('CREATE TABLE search_history (normalized_query TEXT, query TEXT, content_type TEXT, last_used_at INTEGER)')
            connection.execute('CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

        self.state.initialize()
        with sqlite3.connect(self.database_path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn('favorites', tables)

    def test_search_history_persists_deduplicates_orders_and_applies_limit(self):
        self.state.record_search('  The   Last of Us ', 'shows')
        self.state.record_search('Arrival', 'movies')
        self.state.record_search('the last of us', 'shows')

        searches = self.state.list_searches()
        self.assertEqual(2, len(searches))
        self.assertEqual('the last of us', searches[0]['query'])
        self.assertEqual('shows', searches[0]['content_type'])

        limited = UserState(self.database_path, history_limit=2, clock=self.clock)
        limited.record_search('Dune', 'all')
        self.assertEqual(['Dune', 'the last of us'], [row['query'] for row in limited.list_searches()])

        restarted = UserState(self.database_path)
        self.assertEqual(['Dune', 'the last of us'], [row['query'] for row in restarted.list_searches()])
        self.assertTrue(restarted.remove_search('THE LAST OF US', 'shows'))
        self.assertFalse(restarted.remove_search('The Last of Us', 'shows'))
        restarted.clear_searches()
        self.assertEqual([], restarted.list_searches())

    def test_empty_queries_are_ignored(self):
        self.assertFalse(self.state.record_search('   ', 'all'))
        self.assertEqual([], self.state.list_searches())

    def test_two_instances_complete_concurrent_writes(self):
        first = UserState(self.database_path)
        second = UserState(self.database_path)

        def write(index):
            state = first if index % 2 else second
            self.assertTrue(state.record_search('Query {}'.format(index), 'all'))

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write, range(16)))

        self.assertEqual(16, len(UserState(self.database_path).list_searches()))

    def test_corrupt_database_is_reported_without_replacing_it(self):
        with open(self.database_path, 'wb') as database:
            database.write(b'not a sqlite database')

        with self.assertRaisesRegex(UserStateError, 'local user-state database'):
            self.state.list_searches()
        with open(self.database_path, 'rb') as database:
            self.assertEqual(b'not a sqlite database', database.read())


if __name__ == '__main__':
    unittest.main()
