import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode
import httpx

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
    
    api_key = os.getenv("SCRAPEOPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Brak klucza API ScrapeOps na serwerze!")

    params = {
        "api_key": api_key,
        "url": target_url,
        "country": "pl",
        "keep_headers": "true"
    }
    proxy_url = "https://proxy.scrapeops.io/v1/?" + urlencode(params)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "pl-PL,pl;q=0.9"
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.get(proxy_url, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Błąd API ScrapeOps: {response.text[:200]}")
                
            try:
                data = response.json()
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
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"Błąd połączenia z API ({type(exc).__name__}): {exc}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Błąd parsowania danych: {str(e)}")