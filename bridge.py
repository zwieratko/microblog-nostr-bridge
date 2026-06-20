import asyncio
import fcntl
import json
import logging
import os
import requests
import tempfile
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from nostr_sdk import Client, Keys, NostrSigner, RelayUrl, EventBuilder
from config import RELAYS

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
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_posts.json")
LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.lock")
MAX_POSTS_PER_RUN = 5  # Safety cap: max new posts published per cron run


def get_seen_posts() -> set:
    if not os.path.exists(DB_FILE):
        return set()
    with open(DB_FILE, "r") as f:
        try:
            return set(json.load(f))
        except (json.JSONDecodeError, ValueError) as e:
            corrupt_path = DB_FILE + ".corrupt"
            os.replace(DB_FILE, corrupt_path)
            raise RuntimeError(
                f"Corrupt DB file renamed to {corrupt_path} — "
                f"inspect it and delete it to start fresh. Original error: {e}"
            )


def save_seen_posts(seen_set: set) -> None:
    db_dir = os.path.dirname(DB_FILE)
    with tempfile.NamedTemporaryFile("w", dir=db_dir, delete=False, suffix=".tmp") as f:
        json.dump(list(seen_set), f)
        tmp_path = f.name
    os.replace(tmp_path, DB_FILE)


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
    falls back to manual signing if the method is unavailable.

    Raises RuntimeError if the event was not accepted by any relay."""
    builder = EventBuilder.text_note(message)
    try:
        output = await client.send_event_builder(builder)
    except AttributeError:
        # Fallback for older nostr-sdk versions without send_event_builder
        log.debug("send_event_builder not available, falling back to manual signing")
        event = await signer.sign_event_builder(builder)
        output = await client.send_event(event)

    if output.failed:
        for relay_url, reason in output.failed.items():
            log.warning("Relay %s rejected event: %s", relay_url, reason)

    if not output.success:
        raise RuntimeError("Event not accepted by any relay — see relay warnings above")

    log.debug(
        "Event %s confirmed by %d/%d relay(s)",
        output.id,
        len(output.success),
        len(output.success) + len(output.failed),
    )


async def main() -> None:
    if not NSEC:
        log.error("Missing NOSTR_NSEC in .env — aborting")
        return

    with open(LOCK_FILE, "w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.warning("Another instance is already running — skipping this run")
            return

        await _run()


async def _run() -> None:
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
            if new_count >= MAX_POSTS_PER_RUN:
                log.warning(
                    "Reached MAX_POSTS_PER_RUN (%d) — remaining new posts will be "
                    "published in subsequent runs",
                    MAX_POSTS_PER_RUN,
                )
                break

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
