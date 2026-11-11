import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
import notify
import io
import json
from urllib.error import HTTPError


def release(number, tag='rust-v1.2.3', **extra):
    return dict(id=number, tag_name=tag, draft=False, prerelease=False,
                published_at='2026-01-01T00:00:00Z', **extra)


class NotificationTests(unittest.TestCase):
    def graphql_page(self, number, more=False, cursor=None, prerelease=False):
        return {'data': {'repository': {'releases': {
            'nodes': [dict(databaseId=number, tagName='rust-v1.2.3', isDraft=False,
                           isPrerelease=prerelease, publishedAt='2026-01-01T00:00:00Z',
                           url='https://github.com/openai/codex/releases', description='Notes')],
            'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}}}}

    @patch.dict(notify.os.environ, {'GH_TOKEN': 'test-token'})
    def test_graphql_pagination_and_filtering(self):
        with patch.object(notify, 'read_page', side_effect=[
                self.graphql_page(1, True, 'next', prerelease=True),
                self.graphql_page(2)]) as read:
            result = notify.fetch_releases()
        self.assertEqual([r['id'] for r in result], [2])
        self.assertEqual(result[0]['body'], 'Notes')
        requests = [json.loads(call.args[0].data) for call in read.call_args_list]
        self.assertIsNone(requests[0]['variables']['cursor'])
        self.assertEqual(requests[1]['variables']['cursor'], 'next')

    @patch.dict(notify.os.environ, {'GH_TOKEN': 'test-token'})
    def test_graphql_partial_errors_abort(self):
        response = self.graphql_page(1)
        response['errors'] = [{'message': 'Partial failure'}]
        with patch.object(notify, 'read_page', return_value=response):
            with self.assertRaises(ValueError):
                notify.fetch_releases()

    @patch.dict(notify.os.environ, {'GH_TOKEN': 'test-token'})
    def test_graphql_repeated_cursor_aborts(self):
        with patch.object(notify, 'read_page', return_value=self.graphql_page(1, True, 'same')):
            with self.assertRaises(ValueError):
                notify.fetch_releases()

    def test_read_retries_gateway_timeout(self):
        error = HTTPError('https://api.github.com', 504, 'Timeout', {}, None)
        with patch.object(notify.urllib.request, 'urlopen',
                          side_effect=[error, io.BytesIO(b'[]')]) as read, \
                patch.object(notify.time, 'sleep'):
            self.assertEqual(notify.read_page('https://api.github.com'), [])
            self.assertEqual(read.call_count, 2)

    def test_read_does_not_retry_auth_failure(self):
        error = HTTPError('https://api.github.com', 401, 'Unauthorized', {}, None)
        with patch.object(notify.urllib.request, 'urlopen', side_effect=error) as read:
            with self.assertRaises(HTTPError):
                notify.read_page('https://api.github.com')
            self.assertEqual(read.call_count, 1)

    def test_read_retry_limit(self):
        error = HTTPError('https://api.github.com', 504, 'Timeout', {}, None)
        with patch.object(notify.urllib.request, 'urlopen', side_effect=error) as read, \
                patch.object(notify.time, 'sleep'):
            with self.assertRaises(HTTPError):
                notify.read_page('https://api.github.com')
            self.assertEqual(read.call_count, 4)

    def test_filter(self):
        self.assertTrue(notify.stable(release(1)))
        for tag in ['rust-v1.2.3-alpha.1', 'rust-v1.2.3-rc.1', 'other-v1.2.3']:
            self.assertFalse(notify.stable(release(2, tag)))
        self.assertFalse(notify.stable({**release(3), 'prerelease': True}))
        self.assertFalse(notify.stable({**release(4), 'draft': True}))

    def test_multiple_releases_and_deduplication(self):
        self.assertEqual([r['id'] for r in notify.pending(
            [release(3), release(1), release(2)], {'seen': [1]})], [2, 3])

    def test_baseline_and_failed_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            with patch.object(notify, 'STATE', state), patch.object(notify, 'send') as send:
                with patch.object(notify, 'fetch_releases', return_value=[release(1)]):
                    notify.main()
                send.assert_not_called()
                baseline = state.read_bytes()
                with patch.object(notify, 'fetch_releases', return_value=[release(1), release(2)]):
                    send.side_effect = RuntimeError('SMTP failed')
                    with self.assertRaises(RuntimeError):
                        notify.main()
                    self.assertEqual(baseline, state.read_bytes())
                    send.side_effect = None
                    notify.main()
                    send.reset_mock()
                    notify.main()
                    send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
