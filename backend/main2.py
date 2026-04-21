import os
import asyncio
import json
from curl_cffi import requests
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Załadowanie zmiennych środowiskowych
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "twoj-url-z-supabase")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "twoj-klucz-z-supabase")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Błąd inicjalizacji klienta Supabase: {e}")
    exit(1)

async def get_poznan_cinemas(client: requests.AsyncSession) -> list:
    """Pobiera listę kin Cinema City i filtruje te z Poznania."""
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

        poznan_cinemas = [
            cinema for cinema in all_cinemas
            if cinema.get("addressInfo", {}).get("city") == "Poznań"
        ]

        print(f"Znaleziono {len(poznan_cinemas)} kin w Poznaniu.")
        return poznan_cinemas

    except requests.errors.RequestsError as e:
        print(f"Błąd HTTP podczas pobierania listy kin: {e}")
        return []
    except json.JSONDecodeError:
        print("Błąd dekodowania JSON z listy kin.")
        return []

async def scrape_cinema_city_poznan():
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            # KROK 1: Inicjalizacja sesji i pobranie ciasteczek
            print("Nawiązywanie połączenia z Cinema City...")
            await client.get("https://www.cinema-city.pl/", timeout=60.0)

            # KROK 2: Pobranie kin w Poznaniu
            poznan_cinemas = await get_poznan_cinemas(client)
            if not poznan_cinemas:
                print("Nie znaleziono kin w Poznaniu lub wystąpił błąd. Zakończono.")
                return

            movies_cache = {}  # Pamięć podręczna dla pobranych/dodanych filmów z bazy

            # KROK 3: Iteracja po znalezionych kinach
            for cinema in poznan_cinemas:
                cinema_id_api = cinema.get("id")
                cinema_name = cinema.get("displayName")

                if not cinema_id_api or not cinema_name:
                    continue

                print(f"\n--- Rozpoczynam scraping dla: {cinema_name} (ID: {cinema_id_api}) ---")

                # Upsert kina w Supabase (wymaga nałożonego UNIQUE na kolumnie 'name')
                cinema_res = supabase.table("cinemas").upsert(
                    {"name": cinema_name, "city": "Poznań", "franchise": "Cinema City"},
                    on_conflict="name"
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

                # Iteracja po datach i pobieranie seansów
                for date in dates_list:
                    print(f"-> Analizowanie dnia: {date}")
                    events_url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cinema_id_api}/at-date/{date}"

                    events_response = await client.get(events_url, headers=headers, timeout=60.0)

                    if events_response.status_code != 200:
                        print(f"   Błąd pobierania dnia {date} (Kod: {events_response.status_code})")
                        continue

                    events_data = events_response.json()
                    body = events_data.get("body") or {}
                    films_api_list = body.get("films", [])
                    events_api_list = body.get("events", [])

                    movies_to_upsert = {}
                    for film in films_api_list:
                        title = film.get("name").strip()
                        if title and title not in movies_cache and title not in movies_to_upsert:
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

                            raw_release_year = film.get("releaseYear")
                            release_year = str(raw_release_year).replace('/', ',').split(',')[0].strip() if raw_release_year else None

                            movies_to_upsert[title] = {
                                "title": title, 
                                "cc_movie_type": movie_type,
                                "cc_length": film.get("length"),
                                "cc_poster": film.get("posterLink"),
                                "cc_release_year": release_year
                            }
                            
                    # Zbiorczy Upsert wszystkich nowych filmów na ten dzień
                    if movies_to_upsert:
                        movies_res = supabase.table("movies").upsert(
                            list(movies_to_upsert.values()),
                            on_conflict="title"
                        ).execute()
                        for m in movies_res.data:
                            movies_cache[m["title"]] = m["id"]

                    # Utworzenie mapy z API ID do BAZA ID
                    film_id_map = {}
                    for film in films_api_list:
                        api_film_id = film.get("id")
                        title = film.get("name")
                        if api_film_id and title in movies_cache:
                            film_id_map[api_film_id] = movies_cache[title]
                    
                    new_screenings = {}
                    for event in events_api_list:
                        api_film_id = event.get("filmId")
                        start_time_raw = event.get("eventDateTime")
                        room_name = event.get("auditorium")

                        if not api_film_id or not start_time_raw:
                            continue

                        try:
                            # Zamiana "2026-04-20T20:30:00" na obiekt daty z polską strefą czasową
                            dt_obj = datetime.fromisoformat(start_time_raw)
                            dt_aware = dt_obj.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
                            start_time = dt_aware.isoformat()
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
                        supabase.table("screenings").upsert(
                            list(new_screenings.values()),
                            on_conflict="movie_id,cinema_id,start_time,room_name",
                            ignore_duplicates=True
                        ).execute()
                        
                    print(f"   Wysłano {len(new_screenings)} seansów do bazy (upsert).")

                    await asyncio.sleep(0.5)

            print("\nZakończono zapisywanie danych z Cinema City dla kin w Poznaniu!")

        except Exception as e:
            print(f"Wystąpił błąd w trakcie scrapowania: {str(e)}")

if __name__ == "__main__":
    asyncio.run(scrape_cinema_city_poznan())