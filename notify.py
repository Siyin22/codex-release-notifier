"""Notify by SMTP about stable Codex releases. Standard library only."""
import json
import os
import re
import smtplib
import ssl
import tempfile
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

API = 'https://api.github.com/repos/openai/codex/releases'
STATE = Path(os.environ.get('STATE_FILE', 'state/releases.json'))


def stable(release):
    return (not release.get('draft') and not release.get('prerelease')
            and re.fullmatch(r'rust-v\d+\.\d+\.\d+', release.get('tag_name', '')) is not None)


def fetch_releases():
    releases = []
    for page in range(1, 1001):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'codex-release-notifier'}
        if os.environ.get('GH_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
        request = urllib.request.Request(f'{API}?per_page=100&page={page}', headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError('Unexpected GitHub response')
        releases.extend(r for r in batch if stable(r))
        if len(batch) < 100:
            return releases
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
