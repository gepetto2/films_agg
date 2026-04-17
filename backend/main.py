import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get_multikino_films():
    target_url = "https://www.multikino.pl/api/microservice/showings/cinemas/0011/films"
    

    # Używamy curl_cffi z proxy, co pozwala nam zachować sesję (ciasteczka) i sygnaturę Chrome
    async with requests.AsyncSession(impersonate="chrome") as client:
        try:
            # KROK 1: Wejście na stronę główną, aby Cloudflare nadał nam ciasteczka (np. cf_clearance)
            await client.get("https://www.multikino.pl/", timeout=60.0)
            
            # KROK 2: Właściwe zapytanie do API, przekazując odpowiednie nagłówki
            headers = {"Referer": "https://www.multikino.pl/", "Accept": "application/json"}
            response = await client.get(target_url, headers=headers, timeout=60.0)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Błąd Multikina: {response.text[:200]}")
                
            raw_text = response.text

            try:
                data = json.loads(raw_text)
            except ValueError:
                raise HTTPException(status_code=502, detail=f"Odpowiedź nie jest poprawnym formatem JSON. Fragment: {response.text[:250]}")
            
            parsed_films = []
            films_list = data.get("result", []) if isinstance(data, dict) else []

            for film in films_list:
                title = film.get("filmTitle")
                showings = []
                
                for group in film.get("showingGroups", []):
                    date_name = group.get("date", "").split("T")[0]
                    
                    for session in group.get("sessions", []):
                        # Wyciąganie języka
                        lang_attrs = [
                            attr.get("name") 
                            for attr in session.get("attributes", []) 
                            if attr.get("attributeType") == "Language"
                        ]
                        version = lang_attrs[0] if lang_attrs else "2D" # Domyślnie 2D, jeśli brak info
                        
                        # Czas startu
                        start_time_raw = session.get("startTime", "")
                        time_str = start_time_raw.split("T")[-1][:5] if "T" in start_time_raw else "??:??"
                        
                        showings.append({
                            "date": date_name, 
                            "time": time_str, 
                            "screen": session.get("screenName"), 
                            "version": version,
                        })
                
                if showings:
                    parsed_films.append({"title": title, "showings": showings})
                    
            return parsed_films

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Błąd parsowania danych: {str(e)}")