"""
scan_nostr.py

Scans all Nostr posts by the configured user and prints only those
that have received at least one reaction (like, repost, zap, etc.).

Usage:
    uv run python scan_nostr.py
    uv run python scan_nostr.py --since 2024-01-01
    uv run python scan_nostr.py --limit 500
"""

import asyncio
import argparse
import os
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from nostr_sdk import (
    Client,
    EventId,
    Filter,
    Keys,
    Kind,
    NostrSigner,
    PublicKey,
    RelayUrl,
    Timestamp,
)

load_dotenv()

# --- Configuration ---
NSEC = os.getenv("NOSTR_NSEC")
RELAYS = ["wss://nos.lol", "wss://relay.damus.io", "wss://relay.primal.net"]

BATCH_SIZE = 200       # Events per relay fetch call
FETCH_TIMEOUT = 15     # Seconds to wait for events per batch
REACTION_TIMEOUT = 10  # Seconds to wait for reactions per post

# Reaction kind numbers and their display labels
REACTION_KINDS = {
    6:    "Repost 🔄",
    7:    "Like ❤️",
    9735: "Zap ⚡",
}

KIND_TEXT_NOTE = Kind(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_since(date_str: str) -> Timestamp:
    """Parse an ISO date string (YYYY-MM-DD) into a Nostr Timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return Timestamp.from_secs(int(dt.timestamp()))


def format_timestamp(ts) -> str:
    dt = datetime.fromtimestamp(ts.as_secs(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def reaction_label(kind_value: int, content: str) -> str:
    label = REACTION_KINDS.get(kind_value)
    if label:
        return label
    if content:
        return f"Reaction [{kind_value}] ({content[:30]})"
    return f"Reaction [{kind_value}]"


def content_preview(text: str, width: int = 120) -> str:
    preview = text.replace("\n", " ").strip()
    return preview[:width] + "..." if len(preview) > width else preview


# ---------------------------------------------------------------------------
# Fetch all posts (paginated)
# ---------------------------------------------------------------------------

async def fetch_all_posts(client: Client, pubkey: PublicKey, since: Timestamp, max_posts: int):
    """
    Fetch text notes in reverse-chronological batches until no new events
    are returned or max_posts is reached.
    """
    all_events = {}   # id_hex -> event (dedup across batches)
    until = None      # Start from now, move backwards

    print(f"Fetching posts (batch size: {BATCH_SIZE}, max: {max_posts}) ...")

    while True:
        f = Filter().author(pubkey).kind(KIND_TEXT_NOTE).limit(BATCH_SIZE).since(since)
        if until:
            f = f.until(until)

        try:
            result = await client.fetch_events(f, timedelta(seconds=FETCH_TIMEOUT))
            batch = result.to_vec()
        except Exception as e:
            print(f"Warning: fetch error during pagination: {e}")
            break

        if not batch:
            break

        new_count = 0
        oldest_ts = None

        for event in batch:
            hex_id = event.id().to_hex()
            if hex_id not in all_events:
                all_events[hex_id] = event
                new_count += 1

            ts = event.created_at().as_secs()
            if oldest_ts is None or ts < oldest_ts:
                oldest_ts = ts

        print(f"  Batch: {new_count} new events (total so far: {len(all_events)})")

        if new_count == 0 or len(all_events) >= max_posts:
            break

        # Move the window back: set until = oldest timestamp - 1 second
        until = Timestamp.from_secs(oldest_ts - 1)

    return list(all_events.values())


# ---------------------------------------------------------------------------
# Fetch reactions for a list of event IDs in one query
# ---------------------------------------------------------------------------

async def fetch_reactions_bulk(client: Client, event_ids: list) -> dict:
    """
    Returns a dict: event_id_hex -> list of reaction events.
    Fetches all reactions for all posts in a single relay query.
    """
    reaction_kinds = [Kind(k) for k in REACTION_KINDS.keys()]

    f = Filter().kinds(reaction_kinds).events(event_ids)

    try:
        result = await client.fetch_events(f, timedelta(seconds=REACTION_TIMEOUT))
        reaction_events = result.to_vec()
    except Exception as e:
        print(f"Warning: could not fetch reactions: {e}")
        return {}

    # Group reactions by the referenced event ID
    grouped: dict[str, list] = {}
    for r in reaction_events:
        # The 'e' tag references the post this reaction belongs to
        for tag in r.tags().to_vec():
            tag_vec = tag.as_vec()
            if len(tag_vec) >= 2 and tag_vec[0] == "e":
                ref_id = tag_vec[1]
                grouped.setdefault(ref_id, []).append(r)
                break  # Only use the first 'e' tag

    return grouped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(since_str: str | None, max_posts: int) -> None:
    if not NSEC:
        print("Error: NOSTR_NSEC is missing from .env")
        return

    keys = Keys.parse(NSEC)
    pubkey = keys.public_key()
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    for relay_url in RELAYS:
        try:
            await client.add_relay(RelayUrl.parse(relay_url))
        except Exception as e:
            print(f"Warning: could not add relay {relay_url}: {e}")

    await client.connect()

    try:
        since = parse_since(since_str) if since_str else Timestamp.from_secs(0)

        print(f"User:   {pubkey.to_bech32()}")
        print(f"Since:  {since_str or 'beginning'}")
        print("-" * 70)

        # Step 1: Fetch all posts
        all_posts = await fetch_all_posts(client, pubkey, since, max_posts)

        if not all_posts:
            print("No posts found.")
            return

        all_posts.sort(key=lambda e: e.created_at().as_secs(), reverse=True)
        print(f"\nTotal posts fetched: {len(all_posts)}")
        print("Fetching reactions for all posts ...")

        # Step 2: Fetch all reactions in one bulk query
        event_ids = [e.id() for e in all_posts]
        reactions_by_post = await fetch_reactions_bulk(client, event_ids)

        # Step 3: Print only posts that have at least one reaction
        posts_with_reactions = [
            p for p in all_posts
            if p.id().to_hex() in reactions_by_post
        ]

        print(f"Posts with reactions: {len(posts_with_reactions)} / {len(all_posts)}")
        print("=" * 70)

        if not posts_with_reactions:
            print("No posts with reactions found.")
            return

        for post in posts_with_reactions:
            hex_id = post.id().to_hex()
            reactions = reactions_by_post[hex_id]

            print(f"\nDate:     {format_timestamp(post.created_at())}")
            print(f"ID:       {hex_id}")
            print(f"Content:  {content_preview(post.content())}")

            # Count by kind
            counts: dict[int, int] = {}
            for r in reactions:
                k = r.kind().as_u16()
                counts[k] = counts.get(k, 0) + 1

            summary = "  ".join(
                f"{reaction_label(k, '')} ×{n}" for k, n in sorted(counts.items())
            )
            print(f"Reactions ({len(reactions)}): {summary}")

            # Detail lines
            for r in sorted(reactions, key=lambda x: x.created_at().as_secs()):
                kind_val = r.kind().as_u16()
                label = reaction_label(kind_val, r.content())
                try:
                    author = r.author().to_bech32()
                except Exception:
                    author = "(unknown)"
                print(f"  - {label}  by {author}")

        print("\n" + "=" * 70)
        print(f"Done. {len(posts_with_reactions)} post(s) with reactions shown.")

    finally:
        await client.disconnect()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan all Nostr posts and show those with reactions."
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Only scan posts published on or after this date (default: all time)",
        default=None,
    )
    parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        help=f"Maximum number of posts to fetch (default: 2000)",
        default=2000,
    )
    args = parser.parse_args()
    asyncio.run(main(args.since, args.limit))
