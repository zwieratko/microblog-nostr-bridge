# --- Shared relay configuration ---
# All scripts (bridge, inspect_nostr, scan_nostr) import RELAYS from here.
# Publish and query relays are intentionally kept identical to ensure
# that posts written by bridge.py are always visible in the utility scripts.
RELAYS: list[str] = [
    "wss://nos.lol",
    "wss://relay.damus.io",
    "wss://relay.snort.social",
    "wss://relay.primal.net",
]
