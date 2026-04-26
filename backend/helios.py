import re
import execjs
from curl_cffi import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

async def fetch_nuxt_state(client: requests.AsyncSession, url: str) -> dict:
    """Pobiera i dekoduje stan window.__NUXT__ ze wskazanej strony."""
    try:
        response = await client.get(url, timeout=60.0)
        if response.status_code != 200:
            print(f"Błąd HTTP {response.status_code} dla {url}")
            return {}
            
        match = re.search(r'window\.__NUXT__=(.*?);</script>', response.text, re.DOTALL)
        if not match:
            return {}
            
        return execjs.eval(match.group(1))
    except Exception as e:
        print(f"Błąd pobierania/parsowania {url}: {e}")
        return {}

async def get_target_cinemas(client: requests.AsyncSession, cities: list) -> list:
    """Pobiera listę kin Helios poprzez parsowanie obiektu stanu window.__NUXT__."""
    print("Pobieranie listy kin z Helios (parsowanie window.__NUXT__)...")
    nuxt_state = await fetch_nuxt_state(client, "https://helios.pl/")
    cinemas_data = nuxt_state.get("state", {}).get("core", {}).get("cinemas", [])

    target_cinemas = [
        {
            "id": c.get("sourceId"),
            "name": c.get("name"),
            "city": c.get("city"),
            "slug_city": c.get("slugCity"),
            "slug": c.get("slug")
        }
        for c in cinemas_data if c.get("city") in cities
    ]
            
    print(f"Znaleziono {len(target_cinemas)} kin Helios dla miast: {', '.join(cities)}.")
    return target_cinemas

async def scrape_and_save(supabase, cities=["Poznań"]):
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            print("Nawiązywanie połączenia z Heliosem...")
            target_cinemas = await get_target_cinemas(client, cities)
            if not target_cinemas:
                print("Nie znaleziono kin Heliosa. Zakończono.")
                return

            movies_cache = {}

            for cinema in target_cinemas:
                cinema_name = cinema['name']
                print(f"\n--- Repertuar dla: {cinema_name} ---")

                # Zapis kina do bazy
                cinema_res = supabase.table("cinemas").upsert(
                    {"name": cinema_name, "city": cinema['city'], "franchise": "Helios"},
                    on_conflict="name,franchise"
                ).execute()
                db_cinema_id = cinema_res.data[0]["id"]

                # --- POBIERANIE INFORMACJI O SALACH Z REST API ---
                cinema_source_id = cinema['id']
                screens_url = f"https://restapi.helios.pl/api/cinema/{cinema_source_id}/screen"
                screens_mapping = {}
                try:
                    screens_resp = await client.get(screens_url, timeout=30.0)
                    if screens_resp.status_code == 200:
                        for screen in screens_resp.json():
                            screens_mapping[screen["id"]] = screen.get("name", "")
                except Exception as e:
                    print(f"Błąd pobierania sal dla kina {cinema_name}: {e}")

                # --- POBIERANIE LISTY FILMÓW Z NUXT ---
                repertoire_url = f"https://helios.pl/{cinema['slug_city']}/{cinema['slug']}/repertuar"
                nuxt_state = await fetch_nuxt_state(client, repertoire_url)
                repertoire = nuxt_state.get("state", {}).get("repertoire", {})
                
                movies_title_map = {m.get("sourceId"): (m.get("title") or m.get("name")) for m in repertoire.get("list", []) if m.get("sourceId")}

                # --- POBIERANIE SEANSÓW Z REST API ---
                screenings_url = f"https://restapi.helios.pl/api/cinema/{cinema_source_id}/screening"
                try:
                    screenings_resp = await client.get(screenings_url, timeout=30.0)
                    screenings_data = screenings_resp.json() if screenings_resp.status_code == 200 else []
                except Exception as e:
                    print(f"Błąd pobierania seansów dla kina {cinema_name}: {e}")
                    screenings_data = []
                
                # --- POBIERANIE WYDARZEŃ (SEANSÓW SPECJALNYCH) Z REST API ---
                now = datetime.now(ZoneInfo("Europe/Warsaw"))
                date_from = now.strftime("%Y-%m-%dT00:00:00.000")
                date_to = (now + timedelta(days=14)).strftime("%Y-%m-%dT23:59:59.999")
                events_url = f"https://restapi.helios.pl/api/cinema/{cinema_source_id}/event?dateTimeFrom={date_from}&dateTimeTo={date_to}"
                try:
                    events_resp = await client.get(events_url, timeout=30.0)
                    events_data = events_resp.json() if events_resp.status_code == 200 else []
                except Exception as e:
                    print(f"Błąd pobierania wydarzeń dla kina {cinema_name}: {e}")
                    events_data = []

                if not screenings_data and not events_data:
                    print(f"Brak seansów dla kina {cinema_name}.")
                    continue

                print("Zapisywanie filmów do bazy...")
                movies_to_upsert = {title: {"title": title} for title in movies_title_map.values() if title}
                if movies_to_upsert:
                    movie_res = supabase.table("movies").upsert(
                        list(movies_to_upsert.values()),
                        on_conflict="title"
                    ).execute()
                    movies_cache.update({m["title"]: m["id"] for m in movie_res.data})

                print("Przetwarzanie i zapisywanie seansów do bazy...")
                new_screenings = {}
                
                # 1. Zwykłe seanse
                for scr in screenings_data:
                    movie_id_api = scr.get("movieId")
                    title = movies_title_map.get(movie_id_api)
                    if not title:
                        continue
                        
                    db_movie_id = movies_cache.get(title)
                    
                    start_time_raw = scr.get("screeningTimeFrom")
                    scr_id = scr.get("id")
                    
                    if not db_movie_id or not start_time_raw or not scr_id:
                        continue
                        
                    dt_obj = datetime.fromisoformat(start_time_raw)
                    start_time = dt_obj.isoformat()
                        
                    screen_id = scr.get("screenId")
                    room_name = screens_mapping.get(screen_id, "") if screen_id else ""
                    
                    screening_key = (db_movie_id, db_cinema_id, start_time, room_name)
                    new_screenings[screening_key] = {
                        "movie_id": db_movie_id,
                        "cinema_id": db_cinema_id,
                        "start_time": start_time,
                        "room_name": room_name,
                        "booking_link": f"https://bilety.helios.pl/screen/{scr_id}?cinemaId={cinema_source_id}"
                    }
                            
                # 2. Seanse wydarzeń specjalnych
                for event in events_data:
                    title = event.get("name")
                    db_movie_id = movies_cache.get(title)
                    
                    start_time_raw = event.get("timeFrom")
                    scr_id = event.get("screeningId")
                    
                    if not db_movie_id or not start_time_raw or not scr_id:
                        continue
                        
                    dt_obj = datetime.fromisoformat(start_time_raw)
                    start_time = dt_obj.isoformat()
                        
                    screen_id = event.get("screenId")
                    room_name = screens_mapping.get(screen_id, "") if screen_id else ""
                        
                    screening_key = (db_movie_id, db_cinema_id, start_time, room_name)
                    new_screenings[screening_key] = {
                        "movie_id": db_movie_id,
                        "cinema_id": db_cinema_id,
                        "start_time": start_time,
                        "room_name": room_name,
                        "booking_link": f"https://bilety.helios.pl/screen/{scr_id}?cinemaId={cinema_source_id}"
                    }
                            
                if new_screenings:
                    screenings_list = list(new_screenings.values())
                    for i in range(0, len(screenings_list), 1000):
                        supabase.table("screenings").upsert(
                            screenings_list[i:i+1000],
                            on_conflict="movie_id,cinema_id,start_time,room_name",
                            ignore_duplicates=True
                        ).execute()
                    print(f"Zapisano {len(new_screenings)} seansów do bazy dla kina {cinema_name}.")

            print("\nZakończono zapisywanie danych z Heliosa!")

        except Exception as e:
            print(f"Wystąpił błąd w trakcie scrapowania Heliosa: {str(e)}")
