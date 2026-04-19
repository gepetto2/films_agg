import os
import asyncio
import json
from curl_cffi import requests
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Załadowanie zmiennych środowiskowych
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "twoj-url-z-supabase")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "twoj-klucz-z-supabase")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Błąd inicjalizacji klienta Supabase: {e}")
    exit(1)

async def scrape_cinema_city():
    cinema_id_api = "1078" # ID Kina w API Cinema City
    cinema_name = "Cinema City Poznań Plaza"
    
    # Generowanie daty 'until' (np. rok do przodu)
    until_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    dates_url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/dates/in-cinema/{cinema_id_api}/until/{until_date}"
    
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            # KROK 1: Inicjalizacja sesji i pobranie ciasteczek
            print("Nawiązywanie połączenia z Cinema City...")
            await client.get("https://www.cinema-city.pl/", timeout=60.0)
            
            # KROK 2: Sprawdzenie / Dodanie kina w Supabase
            cinema_res = supabase.table("cinemas").select("id").eq("name", cinema_name).execute()
            if not cinema_res.data:
                cinema_res = supabase.table("cinemas").insert({"name": cinema_name, "city": "Poznań"}).execute()
            db_cinema_id = cinema_res.data[0]["id"]

            # KROK 3: Pobranie dostępnych dat
            print("Pobieranie dostępnych dat...")
            headers = {"Accept": "application/json"}
            dates_response = await client.get(dates_url, headers=headers, timeout=60.0)
            
            if dates_response.status_code != 200:
                print(f"Błąd pobierania dat: {dates_response.status_code}")
                return
                
            dates_data = dates_response.json()
            dates_list = dates_data.get("body", {}).get("dates", [])
            
            if not dates_list:
                print("Brak dostępnych dat w API.")
                return
                
            print(f"Znaleziono {len(dates_list)} dni z seansami. Rozpoczynam pobieranie harmonogramów...")

            # KROK 4: Iteracja po datach i pobieranie seansów
            for date in dates_list:
                print(f"-> Analizowanie dnia: {date}")
                events_url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cinema_id_api}/at-date/{date}"
                
                events_response = await client.get(events_url, headers=headers, timeout=60.0)
                
                if events_response.status_code != 200:
                    print(f"   Błąd pobierania dnia {date} (Kod: {events_response.status_code})")
                    continue
                    
                events_data = events_response.json()
                films_api_list = events_data.get("body", {}).get("films", [])
                events_api_list = events_data.get("body", {}).get("events", [])
                
                # Słownik do mapowania ID filmu z API Cinema City na ID w naszej bazie Supabase
                film_id_map = {}
                
                # Przetwarzanie filmów (Zapis do bazy i mapowanie ID)
                for film in films_api_list:
                    api_film_id = film.get("id")
                    title = film.get("name")
                    if not title:
                        continue

                    # Sprawdzenie w bazie
                    movie_res = supabase.table("movies").select("id").eq("title", title).execute()

                    if not movie_res.data:
                        movie_res = supabase.table("movies").insert({
                            "title": title
                        }).execute()
                        
                    db_movie_id = movie_res.data[0]["id"]
                    film_id_map[api_film_id] = db_movie_id
                
                # Przetwarzanie seansów
                inserted_count = 0
                for event in events_api_list:
                    api_film_id = event.get("filmId")
                    start_time = event.get("eventDateTime")
                    room_name = event.get("auditorium")
                    
                    if not api_film_id or not start_time:
                        continue
                        
                    db_movie_id = film_id_map.get(api_film_id)
                    if not db_movie_id:
                        continue
                        
                    # Sprawdzenie duplikatów
                    existing_screening = supabase.table("screenings").select("id").match({
                        "movie_id": db_movie_id,
                        "cinema_id": db_cinema_id,
                        "start_time": start_time,
                        "room_name": room_name
                    }).execute()
                    
                    if not existing_screening.data:
                        supabase.table("screenings").insert({
                            "movie_id": db_movie_id,
                            "cinema_id": db_cinema_id,
                            "start_time": start_time,
                            "room_name": room_name
                        }).execute()
                        inserted_count += 1
                        
                print(f"   Dodano {inserted_count} nowych seansów.")
                
                # Delikatne opóźnienie, aby nie zaspamować API (Ważne przy scrapowaniu)
                await asyncio.sleep(1)
                
            print("\nZakończono zapisywanie danych z Cinema City!")

        except Exception as e:
            print(f"Wystąpił błąd w trakcie scrapowania: {str(e)}")

if __name__ == "__main__":
    asyncio.run(scrape_cinema_city())