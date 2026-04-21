import asyncio
import json
from curl_cffi import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

async def get_target_cinemas(client: requests.AsyncSession, cities: list) -> list:
    """Pobiera listę kin Cinema City i filtruje te z wybranych miast."""
    # Używamy daty daleko w przyszłości, aby mieć pewność, że dostaniemy wszystkie kina, które mają jakiekolwiek wydarzenia
    until_date = (datetime.now() + timedelta(days=365*2)).strftime("%Y-%m-%d")
    cinemas_url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/cinemas/with-event/until/{until_date}"

    print("Pobieranie listy kin z Cinema City...")
    headers = {"Accept": "application/json"}
    try:
        response = await client.get(cinemas_url, headers=headers, timeout=60.0)
        response.raise_for_status()  # Rzuci wyjątkiem dla kodów 4xx/5xx

        data = response.json()
        all_cinemas = data.get("body", {}).get("cinemas", [])

        target_cinemas = [
            cinema for cinema in all_cinemas
            if cinema.get("addressInfo", {}).get("city") in cities
        ]

        print(f"Znaleziono {len(target_cinemas)} kin dla miast: {', '.join(cities)}.")
        return target_cinemas

    except requests.errors.RequestsError as e:
        print(f"Błąd HTTP podczas pobierania listy kin: {e}")
        return []
    except json.JSONDecodeError:
        print("Błąd dekodowania JSON z listy kin.")
        return []

async def fetch_events_for_date(client: requests.AsyncSession, cinema_id_api, date, headers, sem: asyncio.Semaphore):
    """Funkcja pomocnicza do współbieżnego odpytywania API na dany dzień."""
    async with sem:
        events_url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cinema_id_api}/at-date/{date}"
        try:
            response = await client.get(events_url, headers=headers, timeout=60.0)
            if response.status_code == 200:
                return date, response.json()
        except Exception as e:
            print(f"   Błąd pobierania dnia {date}: {e}")
        return date, None

async def scrape_cinema_city(supabase, cities=["Poznań"]):
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            # KROK 1: Inicjalizacja sesji i pobranie ciasteczek
            print("Nawiązywanie połączenia z Cinema City...")
            await client.get("https://www.cinema-city.pl/", timeout=60.0)

            # KROK 2: Pobranie kin
            target_cinemas = await get_target_cinemas(client, cities)
            if not target_cinemas:
                print("Nie znaleziono kin lub wystąpił błąd. Zakończono.")
                return

            movies_cache = {}  # Pamięć podręczna dla pobranych/dodanych filmów z bazy
            
            print("Pobieranie istniejących filmów z bazy (do weryfikacji daty premiery, plakatów i typu filmu)...")
            all_movies_res = supabase.table("movies").select("title, release_year, poster, movie_type").execute()
            existing_db_movies = {m["title"]: m for m in all_movies_res.data}

            sem = asyncio.Semaphore(10)  # Ograniczenie do max. 10 jednoczesnych połączeń

            # KROK 3: Iteracja po znalezionych kinach
            for cinema in target_cinemas:
                cinema_id_api = cinema.get("id")
                cinema_name = cinema.get("displayName")
                cinema_city = cinema.get("addressInfo", {}).get("city")

                if not cinema_id_api or not cinema_name:
                    continue

                print(f"\n--- Rozpoczynam scraping dla: {cinema_name} (ID: {cinema_id_api}) ---")

                # Upsert kina w Supabase (wymaga nałożonego UNIQUE na kolumnach 'name, franchise')
                cinema_res = supabase.table("cinemas").upsert(
                    {"name": cinema_name, "city": cinema_city, "franchise": "Cinema City"},
                    on_conflict="name,franchise"
                ).execute()
                db_cinema_id = cinema_res.data[0]["id"]

                # Pobranie dostępnych dat
                until_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
                dates_url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/dates/in-cinema/{cinema_id_api}/until/{until_date}"

                print("Pobieranie dostępnych dat...")
                headers = {"Accept": "application/json"}
                dates_response = await client.get(dates_url, headers=headers, timeout=60.0)

                if dates_response.status_code != 200:
                    print(f"Błąd pobierania dat dla kina {cinema_name}: {dates_response.status_code}")
                    continue

                dates_data = dates_response.json()
                dates_list = (dates_data.get("body") or {}).get("dates", [])

                if not dates_list:
                    print(f"Brak dostępnych dat w API dla kina {cinema_name}.")
                    continue

                print(f"Znaleziono {len(dates_list)} dni z seansami. Pobieranie harmonogramów...")

                # Współbieżne pobieranie wydarzeń dla wszystkich dni
                tasks = [fetch_events_for_date(client, cinema_id_api, date, headers, sem) for date in dates_list]
                results = await asyncio.gather(*tasks)

                all_movies_to_upsert = {}
                all_films_api_list = []
                all_events_api_list = []

                # Rozpakowywanie wyników
                for date, events_data in results:
                    if not events_data:
                        continue
                    body = events_data.get("body") or {}
                    all_films_api_list.extend(body.get("films", []))
                    all_events_api_list.extend(body.get("events", []))

                for film in all_films_api_list:
                    # Zabezpieczenie w przypadku braku 'name' w filmie
                    title = (film.get("name") or "").strip()
                    if title and title not in movies_cache and title not in all_movies_to_upsert:
                        attribute_ids = film.get("attributeIds", [])
                        type_mapping = {
                            "marathon": "MARATON",
                            "music-event": "MUZYKA",
                            "sport-event": "SPORT",
                            "sport": "SPORT",
                            "dubbed-lang-uk": "UKRAIŃSKI DUBBING",
                            "special-event": "WYDARZENIE SPECJALNE"
                        }
                        movie_type = next((val for key, val in type_mapping.items() if key in attribute_ids), None)

                        existing_movie = existing_db_movies.get(title, {})
                        if not movie_type:
                            movie_type = existing_movie.get("movie_type")

                        raw_release_year = film.get("releaseYear")
                        release_year = str(raw_release_year).replace('/', ',').split(',')[0].strip() if raw_release_year else None
                        
                        existing_year = existing_movie.get("release_year")
                        if existing_year and release_year:
                            release_year = str(min(int(existing_year), int(release_year))) if str(existing_year).isdigit() and str(release_year).isdigit() else str(min(str(existing_year), str(release_year)))
                        elif existing_year:
                            release_year = existing_year
                            
                        existing_movie["release_year"] = release_year
                        
                        cc_poster = film.get("posterLink")
                        poster = existing_movie.get("poster") if existing_movie.get("poster") else cc_poster
                        existing_movie["poster"] = poster
                        existing_db_movies[title] = existing_movie

                        all_movies_to_upsert[title] = {
                            "title": title, 
                            "movie_type": movie_type,
                            "length": film.get("length"),
                            "poster": poster,
                            "release_year": release_year
                        }
                        
                # Zbiorczy Upsert wszystkich nowych filmów ze wszystkich dni
                if all_movies_to_upsert:
                    movies_res = supabase.table("movies").upsert(
                        list(all_movies_to_upsert.values()),
                        on_conflict="title"
                    ).execute()
                    for m in movies_res.data:
                        movies_cache[m["title"]] = m["id"]

                # Utworzenie mapy z API ID do BAZA ID
                film_id_map = {}
                for film in all_films_api_list:
                    api_film_id = film.get("id")
                    title = (film.get("name") or "").strip()
                    if api_film_id and title in movies_cache:
                        film_id_map[api_film_id] = movies_cache[title]
                
                new_screenings = {}
                for event in all_events_api_list:
                    api_film_id = event.get("filmId")
                    start_time_raw = event.get("eventDateTime")
                    room_name = event.get("auditorium")

                    if not api_film_id or not start_time_raw:
                        continue

                    try:
                        # Zamiana na obiekt daty z polską strefą czasową (zabezpieczenie przed nadpisaniem)
                        dt_obj = datetime.fromisoformat(start_time_raw)
                        if dt_obj.tzinfo is None:
                            dt_obj = dt_obj.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
                        start_time = dt_obj.isoformat()
                    except ValueError:
                        start_time = start_time_raw

                    db_movie_id = film_id_map.get(api_film_id)
                    if not db_movie_id:
                        continue

                    attribute_ids = event.get("attributeIds", [])
                    lang = None
                    if "subbed" in attribute_ids:
                        lang = "NAPISY"
                    elif "dubbed" in attribute_ids:
                        lang = "DUBBING"
                    elif "original-lang-pl" in attribute_ids:
                        lang = "PL"

                    screening_key = (db_movie_id, start_time, room_name)
                    new_screenings[screening_key] = {
                        "movie_id": db_movie_id,
                        "cinema_id": db_cinema_id,
                        "start_time": start_time,
                        "room_name": room_name,
                        "lang": lang,
                        "booking_link": event.get("bookingLink"),
                        "availability_ratio": event.get("availabilityRatio")
                    }

                if new_screenings:
                    screenings_list = list(new_screenings.values())
                    # Paginacja na wypadek bardzo dużej ilości seansów (np. limit zapytań Supabase)
                    for i in range(0, len(screenings_list), 1000):
                        supabase.table("screenings").upsert(
                            screenings_list[i:i+1000],
                            on_conflict="movie_id,cinema_id,start_time,room_name",
                            ignore_duplicates=True
                        ).execute()
                        
                    print(f"Zapisano {len(new_screenings)} seansów do bazy dla kina {cinema_name}.")

            print(f"\nZakończono zapisywanie danych z Cinema City dla miast: {', '.join(cities)}!")

        except Exception as e:
            print(f"Wystąpił błąd w trakcie scrapowania: {str(e)}")

if __name__ == "__main__":
    print("Skrypt uruchom poprzez plik run_scrapers.py")