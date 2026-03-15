import asyncio
import requests
import json
import logging
import os
import time
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from nostr_sdk import Client, Keys, NostrSigner, RelayUrl, EventBuilder

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# --- Configuration ---
JSON_FEED_URL = "https://micro.zwieratko.sk/feed.json"
NSEC = os.getenv("NOSTR_NSEC")
RELAYS = ["wss://nos.lol", "wss://relay.damus.io", "wss://relay.snort.social"]
DB_FILE = "seen_posts.json"


def get_seen_posts() -> set:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try:
                return set(json.load(f))
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("Could not parse %s, starting fresh: %s", DB_FILE, e)
                return set()
    return set()


def save_seen_posts(seen_set: set) -> None:
    with open(DB_FILE, "w") as f:
        json.dump(list(seen_set), f)


def clean_html(html_content: str) -> str:
    """Convert HTML post content to plain text, preserving links and image URLs."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")

    # Replace <a> tags with "text (url)" format
    for a in soup.find_all("a"):
        href = a.get("href")
        if href:
            a.replace_with(f"{a.get_text()} ({href})")

    # Collect image URLs and append them at the end
    image_urls = [img.get("src") for img in soup.find_all("img") if img.get("src")]
    text = soup.get_text(separator="\n").strip()

    if image_urls:
        text += "\n\n" + "\n".join(image_urls)

    return text.strip()


async def send_post(client: Client, signer: NostrSigner, message: str) -> None:
    """Build and send a Nostr text note. Tries send_event_builder first,
    falls back to manual signing if the method is unavailable."""
    builder = EventBuilder.text_note(message)
    try:
        await client.send_event_builder(builder)
    except AttributeError:
        # Fallback for older nostr-sdk versions without send_event_builder
        log.debug("send_event_builder not available, falling back to manual signing")
        event = await signer.sign_event_builder(builder)
        await client.send_event(event)


async def main() -> None:
    if not NSEC:
        log.error("Missing NOSTR_NSEC in .env — aborting")
        return

    keys = Keys.parse(NSEC)
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    # Connect to relays
    for relay_url in RELAYS:
        try:
            await client.add_relay(RelayUrl.parse(relay_url))
        except Exception as e:
            log.warning("Failed to add relay %s: %s", relay_url, e)

    await client.connect()

    try:
        # Fetch feed
        seen_posts = get_seen_posts()
        try:
            response = requests.get(JSON_FEED_URL, timeout=10)
            response.raise_for_status()
            feed = response.json()
        except requests.RequestException as e:
            log.error("Failed to fetch feed: %s", e)
            return

        items = feed.get("items", [])
        new_count = 0

        # Process oldest-first so seen_posts reflects chronological order
        for item in reversed(items):
            post_id = item.get("id")
            if not post_id or post_id in seen_posts:
                continue

            html_content = item.get("content_html", "")
            clean_text = clean_html(html_content)
            url = item.get("url", "")
            full_message = f"{clean_text}\n\nSource: {url}"

            try:
                await send_post(client, signer, full_message)
                log.info("Post sent: %s", post_id)
                seen_posts.add(post_id)
                new_count += 1
                await asyncio.sleep(1)  # Brief pause between posts
            except Exception as e:
                log.error("Failed to send post %s: %s", post_id, e)
                # Continue with remaining posts instead of aborting

        if new_count:
            save_seen_posts(seen_posts)
            log.info("Done — %d new post(s) sent", new_count)
        else:
            log.info("No new posts found")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
