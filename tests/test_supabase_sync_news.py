import unittest
from unittest.mock import patch
import supabase_sync


class SupabaseNewsVisibilityTests(unittest.TestCase):
    def test_news_without_image_is_synced_as_stale_so_web_hides_it(self):
        items = [
            {
                'id': 'with-photo', 'kind': 'news', 'title': 'Con foto', 'text': 'Texto',
                'image_url': 'https://medio.test/foto.jpg', 'published_at': '2026-08-21T12:00:00Z',
                'stale': False,
            },
            {
                'id': 'without-photo', 'kind': 'news', 'title': 'Sin foto', 'text': 'Texto',
                'image_url': '', 'thumbnail_url': '', 'published_at': '2026-08-21T12:00:00Z',
                'stale': False,
            },
        ]
        with patch.object(supabase_sync, '_upsert') as upsert:
            supabase_sync.push_items(object(), items)
        rows = upsert.call_args.args[2]
        by_id = {row['id']: row for row in rows}
        self.assertFalse(by_id['with-photo']['stale'])
        self.assertTrue(by_id['without-photo']['stale'])

    def test_news_with_placeholder_or_logo_image_is_synced_as_stale(self):
        items = [
            {
                'id': 'placeholder', 'kind': 'news', 'title': 'Placeholder', 'text': 'Texto',
                'image_url': 'https://medio.test/assets/placeholder-news.jpg',
                'published_at': '2026-08-21T12:00:00Z', 'stale': False,
            },
            {
                'id': 'logo', 'kind': 'news', 'title': 'Logo', 'text': 'Texto',
                'image_url': 'https://medio.test/images/logo.png',
                'published_at': '2026-08-21T12:00:00Z', 'stale': False,
            },
        ]
        with patch.object(supabase_sync, '_upsert') as upsert:
            supabase_sync.push_items(object(), items)
        rows = upsert.call_args.args[2]
        by_id = {row['id']: row for row in rows}
        self.assertTrue(by_id['placeholder']['stale'])
        self.assertTrue(by_id['logo']['stale'])


if __name__ == '__main__':
    unittest.main()
