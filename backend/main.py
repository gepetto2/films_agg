import os
import json
import asyncio
from curl_cffi import requests
from supabase import create_client, Client

# Pobieranie zmiennych środowiskowych (bezpieczeństwo!)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("BŁĄD: Brak kluczy Supabase w zmiennych środowiskowych.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def scrape_multikino():
    target_url = "https://www.multikino.pl/api/microservice/showings/cinemas/0011/films"
    
    print("Rozpoczynam scrapowanie Multikina...")
    
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            # 1. Odwiedzamy stronę główną, by zainicjować sesję
            await client.get("https://www.multikino.pl/", timeout=30.0)
            
            # 2. Pobieramy dane z API
            headers = {
                "Referer": "https://www.multikino.pl/", 
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            }
            response = await client.get(target_url, headers=headers, timeout=30.0)
            
            if response.status_code != 200:
                print(f"Błąd API Multikina: {response.status_code}")
                return

            data = response.json()
            # API Multikina zwraca listę filmów w kluczu "result"
            films_list = data.get("result", []) if isinstance(data, dict) else []

            if not films_list:
                print("Nie znaleziono żadnych filmów.")
                return

            # 3. Przetwarzamy dane na format zgodny z naszą tabelą
            to_upsert = []
            for film in films_list:
                title = film.get("filmTitle")
                showings = []
                
                for group in film.get("showingGroups", []):
                    # Format daty: RRRR-MM-DD
                    date_raw = group.get("date", "").split("T")[0]
                    
                    for session in group.get("sessions", []):
                        # Wyciąganie godziny (HH:MM)
                        start_time = session.get("startTime", "").split("T")[-1][:5]
                        
                        showings.append({
                            "date": date_raw,
                            "time": start_time,
                            "screen": session.get("screenName"),
                            "version": next((a.get("name") for a in session.get("attributes", []) 
                                           if a.get("attributeType") == "Language"), "2D")
                        })
                
                if title and showings:
                    to_upsert.append({
                        "title": title,
                        "showings": showings # PostgreSQL automatycznie obsłuży to jako JSONB
                    })

            # 4. Wysyłamy do Supabase
            if to_upsert:
                # Upsert na podstawie kolumny 'title' (którą oznaczyliśmy jako UNIQUE w SQL)
                result = supabase.table("films").upsert(
                    to_upsert, 
                    on_conflict="title"
                ).execute()
                print(f"Sukces! Zaktualizowano {len(to_upsert)} filmów w bazie Supabase.")

        except Exception as e:
            print(f"Wystąpił błąd podczas pracy scrapera: {e}")

if __name__ == "__main__":
    asyncio.run(scrape_multikino())