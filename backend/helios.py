import re
import execjs
from curl_cffi import requests

async def get_target_cinemas(client: requests.AsyncSession, cities: list) -> list:
    """Pobiera listę kin Helios poprzez parsowanie obiektu stanu window.__NUXT__."""
    url = "https://helios.pl/"
    print("Pobieranie listy kin z Helios (parsowanie window.__NUXT__)...")
    
    try:
        response = await client.get(url, timeout=60.0)
        if response.status_code != 200:
            print(f"Błąd pobierania listy kin z Heliosa (Kod {response.status_code})")
            return []
            
        html = response.text
        
        match = re.search(r'window\.__NUXT__=(.*?);</script>', html, re.DOTALL)
        if not match:
            print("Nie znaleziono stanu Nuxt na stronie!")
            return []
        
        js_code = match.group(1)
        nuxt_state = execjs.eval(js_code)
        cinemas_data = nuxt_state.get("state", {}).get("core", {}).get("cinemas", [])

        target_cinemas = []
        for cinema in cinemas_data:
            city = cinema.get("city")
            if city in cities:
                target_cinemas.append({
                    "id": cinema.get("sourceId"),
                    "name": cinema.get("name"),
                    "city": city,
                    "slug_city": cinema.get("slugCity"),
                    "slug": cinema.get("slug")
                })
                
        print(f"Znaleziono {len(target_cinemas)} kin Helios dla miast: {', '.join(cities)}.")
        return target_cinemas
        
    except Exception as e:
        print(f"Błąd podczas pobierania kin z Heliosa: {e}")
        return []

async def scrape_and_save(supabase, cities=["Poznań"]):
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            print("Nawiązywanie połączenia z Heliosem...")
            
            target_cinemas = await get_target_cinemas(client, cities)
            if not target_cinemas:
                print("Nie znaleziono kin Heliosa. Zakończono.")
                return
                
            for cinema in target_cinemas:
                cinema_name = cinema['name']
                cinema_city = cinema['city']
                print(f"\n--- Zidentyfikowano {cinema_name} (SourceID: {cinema['id']}) ---")
                
                # Upsert kina w Supabase (wymaga nałożonego UNIQUE na kolumnach 'name, franchise')
                cinema_res = supabase.table("cinemas").upsert(
                    {"name": cinema_name, "city": cinema_city, "franchise": "Helios"},
                    on_conflict="name,franchise"
                ).execute()
                db_cinema_id = cinema_res.data[0]["id"]
                
        except Exception as e:
            print(f"Wystąpił błąd w trakcie scrapowania Heliosa: {str(e)}")
