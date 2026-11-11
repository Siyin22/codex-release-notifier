import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
import notify


def release(number, tag='rust-v1.2.3', **extra):
    return dict(id=number, tag_name=tag, draft=False, prerelease=False,
                published_at='2026-01-01T00:00:00Z', **extra)


class NotificationTests(unittest.TestCase):
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
