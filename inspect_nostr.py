import asyncio
import os
from datetime import timedelta
from dotenv import load_dotenv
from nostr_sdk import Client, Keys, NostrSigner, Filter, Kind, RelayUrl

load_dotenv()

# --- Konfigurácia ---
NSEC = os.getenv("NOSTR_NSEC")
RELAYS = ["wss://nos.lol", "wss://relay.damus.io", "wss://relay.primal.net"]

async def main():
    if not NSEC:
        print("Chyba: Chýba NOSTR_NSEC")
        return

    keys = Keys.parse(NSEC)
    pubkey = keys.public_key()
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    for r in RELAYS:
        await client.add_relay(RelayUrl.parse(r))
    await client.connect()

    print(f"Hľadám príspevky pre: {pubkey.to_bech32()}")
    print("-" * 60)

    # 1. ZVÝŠENÝ LIMIT: Teraz stiahne až 5 príspevkov
    p_filter = Filter().author(pubkey).kind(Kind(1)).limit(5)
    
    try:
        events = await client.fetch_events(p_filter, timedelta(seconds=10))
        event_list = events.to_vec()
    except Exception as e:
        print(f"Chyba pri fetch_events: {e}")
        await client.disconnect()
        return
    
    event_list.sort(key=lambda x: x.created_at().as_secs(), reverse=True)

    if not event_list:
        print("Nenašli sa žiadne príspevky.")
        await client.disconnect()
        return

    for event in event_list:
        e_id = event.id()
        content = event.content()
        created_at = event.created_at().to_human_datetime()
        
        print(f"\nID: {e_id.to_hex()}")
        print(f"Dátum: {created_at}")
        preview = content.replace('\n', ' ')
        print(f"Obsah: {preview[:300]}..." if len(preview) > 300 else f"Obsah: {preview}")

        # 2. Hľadanie reakcií a repostov
        r_filter = Filter().kinds([Kind(7), Kind(6)]).event(e_id)
        
        try:
            reactions = await client.fetch_events(r_filter, timedelta(seconds=5))
            reaction_list = reactions.to_vec()
            
            if reaction_list:
                print(f"--- REAKCIE ({len(reaction_list)}) ---")
                for r in reaction_list:
                    try:
                        # BEZPEČNÉ PARSOVANIE:
                        # Skontrolujeme, či je číslo 6 v textovej reprezentácii Kind
                        is_repost = "6" in str(r.kind())
                        r_type = "Repost 🔄" if is_repost else f"Reakcia ❤️ ({r.content()})"
                        
                        # Návrat k author()
                        r_author = r.author().to_bech32()[:99] + "..."
                        
                        print(f"  - {r_type} od {r_author}")
                    except Exception as inner_e:
                        print(f"  - (Chyba pri výpise detailu reakcie: {inner_e})")
            else:
                print("--- Žiadne reakcie ---")
        except Exception as e:
            print(f"--- Nepodarilo sa načítať reakcie: {e} ---")
            
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

