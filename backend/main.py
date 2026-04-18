import os
import asyncio
import json
from curl_cffi import requests
from supabase import create_client, Client
from dotenv import load_dotenv

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
            cinema_name = "Multikino 0011" # Możesz dostosować nazwę wg potrzeb
            cinema_res = supabase.table("cinemas").select("id").eq("name", cinema_name).execute()
            if not cinema_res.data:
                cinema_res = supabase.table("cinemas").insert({"name": cinema_name, "city": "Nieznane"}).execute()
            cinema_id = cinema_res.data[0]["id"]

            films_list = data.get("result", []) if isinstance(data, dict) else []
            print(f"Pobrano {len(films_list)} filmów. Zapisywanie do bazy...")

            for film in films_list:
                title = film.get("filmTitle")
                if not title:
                    continue
                    
                # Sprawdzenie / Dodanie filmu
                movie_res = supabase.table("movies").select("id").eq("title", title).execute()
                if not movie_res.data:
                    movie_res = supabase.table("movies").insert({"title": title}).execute()
                movie_id = movie_res.data[0]["id"]
                
                for group in film.get("showingGroups", []):
                    for session in group.get("sessions", []):
                        start_time_raw = session.get("startTime", "")
                        if not start_time_raw:
                            continue
                            
                        screen_name = session.get("screenName", "")
                        
                        # Sprawdzenie czy ten konkretny seans już istnieje (zapobieganie duplikatom)
                        existing_screening = supabase.table("screenings").select("id").match({
                            "movie_id": movie_id,
                            "cinema_id": cinema_id,
                            "start_time": start_time_raw,
                            "room_name": screen_name
                        }).execute()
                        
                        if not existing_screening.data:
                            supabase.table("screenings").insert({
                                "movie_id": movie_id,
                                "cinema_id": cinema_id,
                                "start_time": start_time_raw,
                                "room_name": screen_name
                            }).execute()
                            
            print("Zakończono zapisywanie danych!")

        except Exception as e:
            print(f"Wystąpił błąd: {str(e)}")

if __name__ == "__main__":
    asyncio.run(scrape_and_save())