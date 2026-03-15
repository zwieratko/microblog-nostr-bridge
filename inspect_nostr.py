import asyncio
import os
from datetime import timedelta
from dotenv import load_dotenv
from nostr_sdk import Client, Keys, Kind, NostrSigner, Filter, RelayUrl

load_dotenv()

# --- Configuration ---
NSEC = os.getenv("NOSTR_NSEC")
RELAYS = ["wss://nos.lol", "wss://relay.damus.io", "wss://relay.primal.net"]
FETCH_LIMIT = 5       # Number of recent posts to inspect
FETCH_TIMEOUT = 10    # Seconds to wait for events from relays
REACTION_TIMEOUT = 5  # Seconds to wait for reactions per post

KIND_TEXT_NOTE = Kind(1)
KIND_REPOST = Kind(6)
KIND_REACTION = Kind(7)


async def main() -> None:
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
        print(f"Fetching posts for: {pubkey.to_bech32()}")
        print("-" * 60)

        # Fetch recent text notes by this author
        p_filter = Filter().author(pubkey).kind(KIND_TEXT_NOTE).limit(FETCH_LIMIT)

        try:
            events = await client.fetch_events(p_filter, timedelta(seconds=FETCH_TIMEOUT))
            event_list = events.to_vec()
        except Exception as e:
            print(f"Error fetching posts: {e}")
            return

        if not event_list:
            print("No posts found.")
            return

        # Sort newest first
        event_list.sort(key=lambda x: x.created_at().as_secs(), reverse=True)

        for event in event_list:
            e_id = event.id()
            content = event.content()
            created_at = event.created_at().to_human_datetime()

            print(f"\nID:      {e_id.to_hex()}")
            print(f"Date:    {created_at}")

            preview = content.replace("\n", " ")
            if len(preview) > 300:
                print(f"Content: {preview[:300]}...")
            else:
                print(f"Content: {preview}")

            # Fetch reactions (kind 7) and reposts (kind 6) for this event
            r_filter = Filter().kinds([KIND_REACTION, KIND_REPOST]).event(e_id)

            try:
                reactions = await client.fetch_events(
                    r_filter, timedelta(seconds=REACTION_TIMEOUT)
                )
                reaction_list = reactions.to_vec()

                if reaction_list:
                    print(f"--- Reactions ({len(reaction_list)}) ---")
                    for r in reaction_list:
                        try:
                            is_repost = r.kind() == KIND_REPOST
                            if is_repost:
                                r_type = "Repost 🔄"
                            else:
                                r_type = f"Reaction ❤️  ({r.content()})"

                            r_author = r.author().to_bech32()
                            print(f"  - {r_type} by {r_author}")
                        except Exception as e:
                            print(f"  - (Error reading reaction detail: {e})")
                else:
                    print("--- No reactions ---")

            except Exception as e:
                print(f"--- Could not fetch reactions: {e} ---")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
