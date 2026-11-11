"""Notify by SMTP about stable Codex releases. Standard library only."""
import json
import os
import re
import smtplib
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

API = 'https://api.github.com/graphql'
RELEASE_QUERY = '''
query($cursor: String) {
  repository(owner: "openai", name: "codex") {
    releases(first: 100, after: $cursor) {
      nodes { databaseId tagName isDraft isPrerelease publishedAt url description }
      pageInfo { hasNextPage endCursor }
    }
  }
}
'''
STATE = Path(os.environ.get('STATE_FILE', 'state/releases.json'))


def read_page(request):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)


def stable(release):
    return (not release.get('draft') and not release.get('prerelease')
            and re.fullmatch(r'rust-v\d+\.\d+\.\d+', release.get('tag_name', '')) is not None)


def fetch_releases():
    releases = []
    cursor = None
    cursors = set()
    headers = {'Content-Type': 'application/json', 'User-Agent': 'codex-release-notifier',
               'Authorization': 'Bearer ' + os.environ['GH_TOKEN']}
    for _ in range(1000):
        request = urllib.request.Request(API, headers=headers, data=json.dumps({
            'query': RELEASE_QUERY, 'variables': {'cursor': cursor}}).encode('utf-8'))
        result = read_page(request)
        if result.get('errors'):
            raise ValueError('GitHub GraphQL returned errors; state not advanced')
        connection = result['data']['repository']['releases']
        batch = [dict(id=r['databaseId'], tag_name=r['tagName'], draft=r['isDraft'],
                      prerelease=r['isPrerelease'], published_at=r['publishedAt'],
                      html_url=r['url'], body=r['description']) for r in connection['nodes']]
        releases.extend(r for r in batch if stable(r))
        if not connection['pageInfo']['hasNextPage']:
            return releases
        cursor = connection['pageInfo']['endCursor']
        if not cursor or cursor in cursors:
            raise ValueError('Invalid GitHub pagination cursor; state not advanced')
        cursors.add(cursor)
    raise RuntimeError('Pagination limit reached; state not advanced')


def pending(releases, state):
    seen = set(state['seen'])
    return sorted((r for r in releases if r['id'] not in seen),
                  key=lambda r: (r['published_at'], r['id']))


def send(releases):
    sender = os.environ['SMTP_USER']
    recipient = os.environ['MAIL_TO']
    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = 'Codex CLI 正式版更新：' + ', '.join(r['tag_name'] for r in releases)
    parts = ['发现新的 Codex CLI 正式版：\n']
    for release in releases:
        parts.append(f"{release['tag_name']}\n发布时间：{release['published_at']}\n"
                     f"{release['html_url']}\n\n{(release.get('body') or '')[:12000]}\n")
    message.set_content('\n'.join(parts))
    with smtplib.SMTP_SSL(os.environ.get('SMTP_HOST', 'smtp.163.com'),
                          int(os.environ.get('SMTP_PORT', '465')),
                          timeout=30, context=ssl.create_default_context()) as smtp:
        smtp.login(sender, os.environ['SMTP_PASSWORD'])
        smtp.send_message(message)


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=STATE.parent,
                                     delete=False) as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        temporary = file.name
    os.replace(temporary, STATE)


def main():
    releases = fetch_releases()
    if not releases:
        raise RuntimeError('No stable releases found; state not advanced')
    if not STATE.exists():
        save({'seen': sorted(r['id'] for r in releases),
              'initialized_at': datetime.now(timezone.utc).isoformat()})
        print('Initialized baseline; no historical emails sent.')
        return
    state = json.loads(STATE.read_text(encoding='utf-8'))
    updates = pending(releases, state)
    if updates:
        send(updates)
        state['seen'] = sorted(set(state['seen']) | {r['id'] for r in updates})
        save(state)
        print(f'SMTP accepted notification for {len(updates)} release(s).')
    else:
        print('No new stable releases.')


if __name__ == '__main__':
    main()
