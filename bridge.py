import asyncio
import requests
import json
import os
import time
from dotenv import load_dotenv
from bs4 import BeautifulSoup
# Pridaný RelayUrl do importov
from nostr_sdk import Client, Keys, NostrSigner, RelayUrl, EventBuilder

load_dotenv()

# --- Konfigurácia ---
JSON_FEED_URL = "https://micro.zwieratko.sk/feed.json"
NSEC = os.getenv("NOSTR_NSEC")
RELAYS = ["wss://nos.lol", "wss://relay.damus.io", "wss://relay.snort.social"]
DB_FILE = "seen_posts.json"

def get_seen_posts():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            try: return set(json.load(f))
            except: return set()
    return set()

def save_seen_posts(seen_set):
    with open(DB_FILE, 'w') as f:
        json.dump(list(seen_set), f)

def clean_html(html_content):
    if not html_content: return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for a in soup.find_all('a'):
        if a.get('href'):
            a.replace_with(f"{a.get_text()} ({a.get('href')})")
    
    image_urls = [img.get('src') for img in soup.find_all('img') if img.get('src')]
    text = soup.get_text(separator="\n").strip()
    if image_urls:
        text += "\n\n" + "\n".join(image_urls)
    return text.strip()

async def main():
    if not NSEC:
        print("Chyba: Chýba NOSTR_NSEC v .env")
        return

    # 1. Inicializácia kľúčov a signera
    keys = Keys.parse(NSEC)
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    # 2. Pridanie relayov s pretypovaním na RelayUrl
    for r in RELAYS:
        try:
            url = RelayUrl.parse(r) # Toto premení string na RelayUrl objekt
            await client.add_relay(url)
        except Exception as e:
            print(f"Nepodarilo sa spracovať relay URL {r}: {e}")
    
    await client.connect()

    # 3. Kontrola feedu
    seen_posts = get_seen_posts()
    try:
        response = requests.get(JSON_FEED_URL, timeout=10)
        feed = response.json()
    except Exception as e:
        print(f"Chyba feedu: {e}")
        await client.disconnect()
        return

    items = feed.get('items', [])
    new_found = False

    for item in reversed(items):
        post_id = item.get('id')
        if post_id not in seen_posts:
            html_content = item.get('content_html', '')
            clean_text = clean_html(html_content)
            url = item.get('url', '')
            full_message = f"{clean_text}\n\nZdroj: {url}"
            
            try:
                # 1. Vytvoríme builder len s textom
                builder = EventBuilder.text_note(full_message)

                # 2. Skúsime najjednoduchšiu metódu, ktorá v 0.34+ zvyčajne funguje:
                # Klient zoberie builder, podpíše ho tvojím kľúčom a pošle.
                await client.send_event_builder(builder)

                print(f"Príspevok odoslaný: {item.get('id')}")
                new_found = True
                seen_posts.add(post_id)
                await asyncio.sleep(1)
            except Exception as e:
                # Ak send_event_builder neexistuje, skúsime manuálny podpis cez signer:
                try:
                    event = await signer.sign_event_builder(builder)
                    await client.send_event(event)
                    print(f"Príspevok odoslaný (manuálny podpis): {item.get('id')}")
                    new_found = True
                    seen_posts.add(post_id)
                except Exception as e2:
                    print(f"Chyba pri odosielaní {post_id}: {e2}")
                    # Tu si môžeš pre istotu vypísať dostupné metódy, ak to znova zlyhá:
                    # print(f"Dostupné metódy klienta: {dir(client)}")

    if new_found:
        save_seen_posts(seen_posts)
    else:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Žiadne nové príspevky.")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

