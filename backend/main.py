import os
import asyncio
import json
from curl_cffi import requests
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo

# Załadowanie zmiennych z pliku .env do środowiska
load_dotenv()

# Ustawienia Supabase (najlepiej ustawić jako zmienne środowiskowe)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "twoj-url-z-supabase")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "twoj-klucz-z-supabase")

# Inicjalizacja klienta Supabase
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Błąd inicjalizacji klienta Supabase: {e}")
    exit(1)

async def scrape_and_save():
    target_url = "https://www.multikino.pl/api/microservice/showings/cinemas/0011/films"
    
    # Używamy curl_cffi z proxy, co pozwala nam zachować sesję (ciasteczka) i sygnaturę Chrome
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            # KROK 1: Wejście na stronę główną, aby Cloudflare nadał nam ciasteczka (np. cf_clearance)
            print("Rozpoczynam pobieranie ciasteczek...")
            await client.get("https://www.multikino.pl/", timeout=60.0)
            
            # KROK 2: Właściwe zapytanie do API, przekazując odpowiednie nagłówki
            print("Odpytywanie API Multikina...")
            headers = {"Referer": "https://www.multikino.pl/", "Accept": "application/json"}
            response = await client.get(target_url, headers=headers, timeout=60.0)
            
            if response.status_code != 200:
                print(f"Błąd Multikina (Kod {response.status_code}): {response.text[:200]}")
                return
                
            raw_text = response.text

            try:
                data = json.loads(raw_text)
            except ValueError:
                print(f"Odpowiedź nie jest poprawnym formatem JSON. Fragment: {response.text[:250]}")
                return
                
            # KROK 3: Sprawdzenie / Dodanie kina (0011)
            cinema_name = "Poznań Stary Browar" # Możesz dostosować nazwę wg potrzeb
            cinema_res = supabase.table("cinemas").select("id").eq("name", cinema_name).execute()
            if not cinema_res.data:
                cinema_res = supabase.table("cinemas").insert({"name": cinema_name, "city": "Poznań", "franchise": "Multikino"}).execute()
            cinema_id = cinema_res.data[0]["id"]

            films_list = data.get("result", []) if isinstance(data, dict) else []
            print(f"Pobrano {len(films_list)} filmów. Zapisywanie do bazy...")

            # KROK 4: Zbieranie filmów do operacji Upsert
            movies_to_upsert = {}
            for film in films_list:
                title = film.get("filmTitle").strip()
                if not title:
                    continue
                    
                film_attrs = film.get("filmAttributes", [])
                movie_type = (film_attrs[0].get("shortName") or film_attrs[0].get("name")) if film_attrs else None
                if movie_type:
                    movie_type = movie_type.removesuffix(" - wydarzenie specjalne")
                    if movie_type == "FAMILIJNY":
                        movie_type = None

                release_date = film.get("releaseDate")
                release_year = release_date[:4] if release_date else None

                movies_to_upsert[title] = {
                    "title": title,
                    "mk_movie_type": movie_type,
                    "mk_length": film.get("runningTime"),
                    "mk_poster": film.get("posterImageSrc"),
                    "mk_release_year": release_year,
                    "mk_description": film.get("synopsisShort"),
                }
                
            movies_cache = {}
            if movies_to_upsert:
                movie_res = supabase.table("movies").upsert(
                    list(movies_to_upsert.values()),
                    on_conflict="title"
                ).execute()
                for m in movie_res.data:
                    movies_cache[m["title"]] = m["id"]

            # KROK 5: Zbieranie seansów do operacji Upsert
            new_screenings = {}
            for film in films_list:
                title = film.get("filmTitle", "").strip()
                movie_id = movies_cache.get(title)
                if not movie_id:
                    continue

                for group in film.get("showingGroups", []):
                    for session in group.get("sessions", []):
                        start_time_raw = session.get("startTime", "")
                        if not start_time_raw:
                            continue
                            
                        try:
                            dt_obj = datetime.fromisoformat(start_time_raw)
                            dt_aware = dt_obj.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
                            start_time = dt_aware.isoformat()
                        except ValueError:
                            start_time = start_time_raw
                            
                        screen_name = session.get("screenName", "")
                        booking_url = session.get("bookingUrl", "")
                        if booking_url and not booking_url.startswith("http"):
                            booking_url = f"https://www.multikino.pl{booking_url}"
                        
                        # Wyciągnięcie odpowiedniej wartości dla kolumny lang
                        lang = None
                        for attr in session.get("attributes", []):
                            if attr.get("attributeType") == "Language":
                                lang = attr.get("name")
                                break
                        
                        screening_key = (movie_id, start_time, screen_name)
                        new_screenings[screening_key] = {
                            "movie_id": movie_id,
                            "cinema_id": cinema_id,
                            "start_time": start_time,
                            "room_name": screen_name,
                            "lang": lang,
                            "booking_link": booking_url
                        }
                            
            if new_screenings:
                supabase.table("screenings").upsert(
                    list(new_screenings.values()),
                    on_conflict="movie_id,cinema_id,start_time,room_name",
                    ignore_duplicates=True
                ).execute()
                print(f"Zapisano {len(new_screenings)} seansów (upsert).")

            print("Zakończono zapisywanie danych!")

        except Exception as e:
            print(f"Wystąpił błąd: {str(e)}")

if __name__ == "__main__":
    asyncio.run(scrape_and_save())