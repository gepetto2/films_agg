import re
import asyncio
import execjs
from curl_cffi import requests
from datetime import datetime
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

                # Pobranie repertuaru dla danego kina
                repertoire_url = f"https://helios.pl/{cinema['slug_city']}/{cinema['slug']}/repertuar"
                nuxt_state = await fetch_nuxt_state(client, repertoire_url)

                repertoire = nuxt_state.get("state", {}).get("repertoire", {})
                
                # Tworzymy mapę filmów po ich ID, aby łatwo znaleźć tytuł
                movies_title_map = {m.get("_id"): m.get("title") for m in repertoire.get("list", []) if m.get("_id")}
                screenings_by_date = repertoire.get("screenings", {})

                if not screenings_by_date:
                    print(f"Brak seansów dla kina {cinema_name}.")
                    continue

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

                sem = asyncio.Semaphore(20)
                async def fetch_screening_screen_id(scr_id):
                    url = f"https://restapi.helios.pl/api/cinema/{cinema_source_id}/screening/{scr_id}"
                    async with sem:
                        try:
                            resp = await client.get(url, timeout=15.0)
                            if resp.status_code == 200:
                                return scr_id, resp.json().get("screenId")
                        except Exception:
                            pass
                    return scr_id, None

                screening_tasks = [
                    fetch_screening_screen_id(scr.get("sourceId"))
                    for movies_data in screenings_by_date.values()
                    for movie_info in movies_data.values()
                    for scr in movie_info.get("screenings", [])
                    if scr.get("sourceId")
                ]
                
                if screening_tasks:
                    print(f"Pobieranie szczegółów {len(screening_tasks)} seansów w celu ustalenia sal (może to chwilę potrwać)...")
                    screening_results = await asyncio.gather(*screening_tasks)
                    screening_screen_map = dict(screening_results)
                else:
                    screening_screen_map = {}
                # -------------------------------------------------

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
                for date, movies_data in screenings_by_date.items():
                    for movie_id, movie_info in movies_data.items():
                        title = movies_title_map.get(movie_id)
                        db_movie_id = movies_cache.get(title)
                        
                        if not db_movie_id:
                            continue
                            
                        for scr in movie_info.get("screenings", []):
                            start_time_raw = scr.get("timeFrom")
                            if not start_time_raw:
                                continue
                                
                            dt_obj = datetime.strptime(start_time_raw, "%Y-%m-%d %H:%M:%S")
                            start_time = dt_obj.replace(tzinfo=ZoneInfo("Europe/Warsaw")).isoformat()
                                
                            scr_id = scr.get("sourceId")
                            screen_id = screening_screen_map.get(scr_id)
                            room_name = screens_mapping.get(screen_id, "") if screen_id else ""
                            
                            screening_key = (db_movie_id, db_cinema_id, start_time, room_name)
                            new_screenings[screening_key] = {
                                "movie_id": db_movie_id,
                                "cinema_id": db_cinema_id,
                                "start_time": start_time,
                                "room_name": room_name,
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
