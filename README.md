# Micro.blog -> Nostr Bridge

Automatically mirrors posts from a [micro.blog](https://micro.blog) JSON feed to the [Nostr](https://nostr.com) decentralized network.

## How it works

`bridge.py` fetches the JSON feed from your micro.blog site, checks which posts have already been sent (tracked in `seen_posts.json`), and publishes any new ones as Nostr text notes (kind 1) to a configured list of relays.

`inspect_nostr.py` is a diagnostic utility that fetches your most recent Nostr posts and displays any reactions or reposts they have received.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Setup

**1. Clone the repository**
```bash
git clone https://github.com/youruser/microblog-nostr-bridge.git
cd microblog-nostr-bridge
```

**2. Install dependencies**
```bash
uv sync
```

**3. Configure environment**
```bash
cp .env.example .env
```
Edit `.env` and fill in your Nostr private key (see `.env.example` for details).

**4. Run manually**
```bash
uv run python bridge.py
```

**5. Set up as a cron job** (e.g. check every 15 minutes)
```bash
crontab -e
```
```
*/15 * * * * cd /path/to/microblog-nostr-bridge && uv run bridge.py >> cron.log 2>&1
```

## Utilities

**Inspect your recent Nostr posts and reactions:**
```bash
uv run python inspect_nostr.py
```

## Configuration

All configuration is done in `bridge.py` at the top of the file:

| Variable | Description |
|---|---|
| `JSON_FEED_URL` | Your micro.blog JSON feed URL |
| `RELAYS` | List of Nostr relay WebSocket URLs |
| `DB_FILE` | Path to the local post-tracking database (default: `seen_posts.json`) |

Your Nostr private key is loaded from the `.env` file — never commit it to the repository.

## Files

| File | Description |
|---|---|
| `bridge.py` | Main bridge — fetches feed and publishes to Nostr |
| `inspect_nostr.py` | Diagnostic tool — view recent posts and reactions |
| `seen_posts.json` | Runtime state — tracks already-sent post IDs (auto-created, git-ignored) |
| `.env` | Your secrets — never committed (git-ignored) |

## License

MIT
