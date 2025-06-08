import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin
import copy
import re

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load env vars ───────────────────────────────────────────────────────────────
load_dotenv()
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ── Base headers for all requests ───────────────────────────────────────────────
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
COOKIES    = os.getenv("COOKIES", "")
BASE_HEADERS = {"User-Agent": USER_AGENT}
if COOKIES:
    BASE_HEADERS["Cookie"] = COOKIES

# ── Initialize Telegram bot client ──────────────────────────────────────────────
client = TelegramClient("hls_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ── Extract the .m3u8 playlist URL from an embed HTML page ────────────────────────
def extract_m3u8_from_embed(embed_url: str) -> str:
    req = urllib.request.Request(embed_url, headers=BASE_HEADERS)
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    # Find any http(s) link ending in .m3u8
    match = re.search(r'(https?://[^\s\'\"]+\.m3u8[^\s\'\"]*)', html)
    if not match:
        raise ValueError("No .m3u8 URL found in embed page HTML.")
    return match.group(1)

# ── Download and merge segments synchronously ───────────────────────────────────
def download_hls_sync(m3u8_url: str, output_ts: str, headers: dict):
    # Fetch playlist
    req = urllib.request.Request(m3u8_url, headers=headers)
    data = urllib.request.urlopen(req).read().decode().splitlines()

    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = [
        line if line.startswith('http') else urljoin(base, line)
        for line in data if line and not line.startswith('#')
    ]

    with open(output_ts, 'wb') as out:
        for i, seg_url in enumerate(segments, 1):
            print(f"[{i}/{len(segments)}] Downloading {seg_url}")
            seg_req = urllib.request.Request(seg_url, headers=headers)
            out.write(urllib.request.urlopen(seg_req).read())

# ── Async wrapper for non-blocking I/O ────────────────────────────────────────────
async def download_hls(m3u8_url: str, output_ts: str, headers: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, output_ts, headers)

# ── Handle incoming Telegram messages ─────────────────────────────────────────────
@client.on(events.NewMessage)
async def on_message(event):
    text = event.raw_text.strip()

    # Prepare headers for download
    headers = copy.deepcopy(BASE_HEADERS)

    # Determine if this is an embed link or direct playlist
    if '/embed/' in text:
        embed_url = text
        # Extract playlist URL first (use BASE_HEADERS)
        await event.reply("🔍 Extracting playlist URL from embed page…")
        try:
            m3u8_url = extract_m3u8_from_embed(embed_url)
        except Exception as e:
            return await event.reply(f"❌ Failed to extract playlist: {e}")
        # Use the embed page as Referer for subsequent requests
        headers['Referer'] = embed_url
    elif text.endswith('.m3u8') or '.m3u8?' in text:
        m3u8_url = text
        # Optionally, set Referer to the domain if needed
        # headers['Referer'] = 'https://anime1u.com/'
    else:
        # Not a link we handle
        return

    status = await event.reply("⏳ Downloading and merging… please wait.")
    tmpdir = tempfile.mkdtemp()
    out_ts = os.path.join(tmpdir, 'output.ts')

    try:
        await download_hls(m3u8_url, out_ts, headers)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    # Send the combined TS file back
    await client.send_file(
        event.chat_id,
        out_ts,
        caption="✅ Here’s your merged stream!",
        force_document=True,
        allow_cache=False,
    )
    await status.delete()

# ── Run the bot ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 Bot started – listening for embed or .m3u8 URLs…")
    client.run_until_disconnected()
