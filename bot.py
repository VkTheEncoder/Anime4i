#!/usr/bin/env python3
import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load creds from .env ──────────────────────────────────────────────────────
load_dotenv()
API_ID   = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
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
