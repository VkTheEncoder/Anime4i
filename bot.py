

import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin
import re

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load environment variables ─────────────────────────────────────────────────
load_dotenv()
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ── Custom headers to mimic browser ──────────────────────────────────────────────
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
REFERER    = os.getenv("REFERER", "")
COOKIES    = os.getenv("COOKIES", "")

HEADERS = {"User-Agent": USER_AGENT}
if REFERER:
    HEADERS["Referer"] = REFERER
if COOKIES:
    HEADERS["Cookie"] = COOKIES

# ── Initialize Telethon client as bot ───────────────────────────────────────────
client = TelegramClient("hls_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ── Extract .m3u8 from embed page ────────────────────────────────────────────────
def extract_m3u8_from_embed(embed_url: str) -> str:
    req = urllib.request.Request(embed_url, headers=HEADERS)
    html = urllib.request.urlopen(req).read().decode('utf-8')
    # Search for any .m3u8 link in the page
    match = re.search(r"(https?://[^\s'\"]+\.m3u8[^\s'\"]*)", html)
    if not match:
        raise ValueError("No .m3u8 URL found in embed page")
    return match.group(1)

# ── Synchronous HLS download + concat ──────────────────────────────────────────
def download_hls_sync(m3u8_url: str, output_path: str):
    # Fetch playlist
    req = urllib.request.Request(m3u8_url, headers=HEADERS)
    playlist = urllib.request.urlopen(req).read().decode().splitlines()

    # Build segment URLs
    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = [
        line if line.startswith('http') else urljoin(base, line)
        for line in playlist
        if line and not line.startswith('#')
    ]

    # Download and merge
    with open(output_path, 'wb') as wf:
        for i, segment_url in enumerate(segments, 1):
            print(f"[{i}/{len(segments)}] Downloading: {segment_url}")
            seg_req = urllib.request.Request(segment_url, headers=HEADERS)
            wf.write(urllib.request.urlopen(seg_req).read())

# ── Async wrapper for the downloader ───────────────────────────────────────────
async def download_hls(m3u8_url: str, output_path: str):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, output_path)

# ── Telegram handler ─────────────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def on_message(event):
    text = event.raw_text.strip()
    # Determine if direct playlist or embed
    if ".m3u8" in text:
        m3u8_url = text
    elif "anime1u.com/embed/" in text:
        await event.reply("🔍 Extracting playlist URL from embed page…")
        try:
            m3u8_url = extract_m3u8_from_embed(text)
        except Exception as e:
            return await event.reply(f"❌ Failed to extract playlist URL: {e}")
    else:
        return  # ignore unrelated messages

    status = await event.reply("⏳ Downloading and merging… this may take a moment.")
    tmpdir = tempfile.mkdtemp()
    output_ts = os.path.join(tmpdir, 'output.ts')

    try:
        await download_hls(m3u8_url, output_ts)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    # Send back the merged .ts file
    await client.send_file(
        event.chat_id,
        output_ts,
        caption="✅ Here's your merged stream!",
        force_document=True,
        allow_cache=False,
    )
    await status.delete()

# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 Bot started – listening for direct and embed URLs…")
    client.run_until_disconnected()

BOT_TOKEN= os.getenv("BOT_TOKEN")

# ── Start Telethon as a Bot ───────────────────────────────────────────────────
client = TelegramClient("hls_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ── HLS downloader (sync) ────────────────────────────────────────────────────
def download_hls_sync(m3u8_url: str, output_path: str):
    # Fetch master/variant playlist
    req = urllib.request.Request(m3u8_url, headers={"User-Agent": "Mozilla/5.0"})
    playlist = urllib.request.urlopen(req).read().decode().splitlines()

    # Build full URLs for each segment
    base = m3u8_url.rsplit("/", 1)[0] + "/"
    segs = [
        line if line.startswith("http") else urljoin(base, line)
        for line in playlist
        if line and not line.startswith("#")
    ]

    # Download + concat
    with open(output_path, "wb") as wf:
        for i, url in enumerate(segs, 1):
            print(f"[{i}/{len(segs)}] {url}")
            data = urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            ).read()
            wf.write(data)

# ── Async wrapper ────────────────────────────────────────────────────────────
async def download_hls(m3u8_url: str, output_path: str):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, output_path)

# ── Telegram handler ──────────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def on_message(event):
    text = event.raw_text.strip()
    if ".m3u8" not in text:
        return  # ignore non-playlist messages

    status = await event.reply("⏳ Downloading and merging, please wait…")
    tmpdir = tempfile.mkdtemp()
    out_ts = os.path.join(tmpdir, "output.ts")

    try:
        await download_hls(text, out_ts)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    # Send back the .ts (up to 50 MB) or fail if too big for Bot API
    await client.send_file(
        event.chat_id,
        out_ts,
        caption="✅ Here’s your merged stream!",
        force_document=True,
        allow_cache=False,
    )
    await status.delete()  # remove the “downloading” message

# ── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Bot started – listening for .m3u8 URLs …")
    client.run_until_disconnected()
