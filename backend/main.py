import os
import json
from supabase import create_client, Client
from curl_cffi import requests
import asyncio

# Dane dostępowe (weźmiesz je z Project Settings -> API w Supabase)
SUPABASE_URL = "TWOJ_URL"
SUPABASE_KEY = "TWOJ_SERVICE_ROLE_KEY" # Użyj service_role do zapisu danych

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def update_database():
    target_url = "https://www.multikino.pl/api/microservice/showings/cinemas/0011/films"
    
    async with requests.AsyncSession(impersonate="chrome") as client:
        # 1. Pobieranie danych (Twój istniejący kod)
        await client.get("https://www.multikino.pl/", timeout=60.0)
        headers = {"Referer": "https://www.multikino.pl/", "Accept": "application/json"}
        response = await client.get(target_url, headers=headers)
        
        data = response.json()
        films_list = data.get("result", [])

        # 2. Mapowanie i przygotowanie do bazy
        to_upsert = []
        for film in films_list:
            title = film.get("filmTitle")
            showings = []
            
            for group in film.get("showingGroups", []):
                date_name = group.get("date", "").split("T")[0]
                for session in group.get("sessions", []):
                    showings.append({
                        "date": date_name,
                        "time": session.get("startTime", "").split("T")[-1][:5],
                        "screen": session.get("screenName")
                    })
            
            if title and showings:
                to_upsert.append({
                    "title": title,
                    "showings": showings,
                    "updated_at": "now()" # Automatyczna data aktualizacji
                })

        # 3. Wysłanie danych do Supabase (Upsert po kolumnie 'title')
        if to_upsert:
            result = supabase.table("films").upsert(
                to_upsert, 
                on_conflict="title"
            ).execute()
            print(f"Zaktualizowano {len(to_upsert)} filmów.")

if __name__ == "__main__":
    asyncio.run(update_database())