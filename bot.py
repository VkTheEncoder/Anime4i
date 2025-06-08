#!/usr/bin/env python3
"""
Telegram HLS Downloader using an MTProto user session (up to 2 GB file uploads).

Configure your `.env`:

    API_ID=123456          # from my.telegram.org
    API_HASH=abcdef1234567890abcdef1234567890
    USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64)
    # Optional cookies for restricted streams
    COOKIES=__stid=...; PHPSESSID=...

Install dependencies:
    pip install -r requirements.txt

Run:
    python3 bot.py

On first launch you’ll be prompted for your phone + code to create a user session.

Send the bot either:
  • A direct `.m3u8` URL
  • An embed link (`https://anime1u.com/embed/...`)

It will download all segments, merge into a single TS, and upload via your user account.
"""
import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin, urlparse
import copy
import re
from html.parser import HTMLParser

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load environment variables ─────────────────────────────────────────────────
load_dotenv()
API_ID   = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# ── Base headers (UA + optional cookies) ────────────────────────────────────────
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
COOKIES    = os.getenv("COOKIES", "")
BASE_HEADERS = {"User-Agent": USER_AGENT}
if COOKIES:
    BASE_HEADERS["Cookie"] = COOKIES

# ── Initialize Telethon as a user (MTProto) ─────────────────────────────────────
session_name = "hls_user_session"
client = TelegramClient(session_name, API_ID, API_HASH)
# This will prompt for phone/code on first run
client.start()

# ── Helper: extract .m3u8 from <source> tags or via regex ─────────────────────────
class M3U8SourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'source':
            for k, v in attrs:
                if k.lower() == 'src' and v and '.m3u8' in v:
                    self.urls.append(v)

def extract_m3u8(embed_url: str, headers: dict) -> str:
    req = urllib.request.Request(embed_url, headers=headers)
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    # 1) Try parsing <source src="…m3u8">
    parser = M3U8SourceParser()
    parser.feed(html)
    if parser.urls:
        return parser.urls[0]
    # 2) Fallback regex
    m = re.search(r"(https?://[^\s'\"]+\.m3u8[^\s'\"]*)", html)
    if m:
        return m.group(1)
    raise ValueError("No .m3u8 URL found in embed page HTML.")

# ── Download & merge HLS segments ────────────────────────────────────────────────
def download_hls_sync(m3u8_url: str, out_ts: str, headers: dict):
    req = urllib.request.Request(m3u8_url, headers=headers)
    playlist = urllib.request.urlopen(req).read().decode().splitlines()
    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = [line if line.startswith('http') else urljoin(base, line)
                for line in playlist if line and not line.startswith('#')]
    with open(out_ts, 'wb') as f:
        for idx, seg in enumerate(segments, 1):
            print(f"[{idx}/{len(segments)}] Downloading: {seg}")
            sreq = urllib.request.Request(seg, headers=headers)
            f.write(urllib.request.urlopen(sreq).read())

async def download_hls(m3u8_url: str, out_ts: str, headers: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, out_ts, headers)

# ── Telegram message handler ─────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def handler(event):
    text = event.raw_text.strip()
    hdrs = copy.deepcopy(BASE_HEADERS)

    # Determine source
    if '/embed/' in text:
        embed = text
        await event.reply("🔍 Extracting playlist from embed page…")
        try:
            playlist_url = extract_m3u8(embed, hdrs)
        except Exception as e:
            return await event.reply(f"❌ Extraction failed: {e}")
        hdrs['Referer'] = embed
    elif text.endswith('.m3u8') or '.m3u8?' in text:
        playlist_url = text
        p = urlparse(playlist_url)
        hdrs['Referer'] = f"{p.scheme}://{p.netloc}/"
    else:
        return

    status = await event.reply("⏳ Downloading and merging… please wait.")
    tmp = tempfile.mkdtemp()
    out_ts = os.path.join(tmp, 'output.ts')

    try:
        await download_hls(playlist_url, out_ts, hdrs)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    # Send via user session (up to 2 GB)
    await client.send_file(
        event.chat_id, out_ts,
        caption="✅ Here’s your merged stream!",
        force_document=True, allow_cache=False
    )
    await status.delete()

# ── Start event loop ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 HLS downloader bot started as user (MTProto). Ready for links…")
    client.run_until_disconnected()
