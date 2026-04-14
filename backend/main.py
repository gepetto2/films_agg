import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MULTIKINO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://multikino.pl/",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

@app.get("/debug-proxy")
async def debug_proxy():
    proxy_url = os.getenv("PROXY_URL")
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    
    async with AsyncSession(proxies=proxies) as client:
        try:
            # Ten serwis zwraca tylko Twój aktualny adres IP
            response = await client.get("https://httpbin.org/ip")
            return {
                "configured_proxy": proxy_url,
                "detected_ip": response.json(),
                "status": "Proxy działa!"
            }
        except Exception as e:
            return {
                "status": "Błąd połączenia",
                "error": str(e),
                "configured_proxy": proxy_url
            }

@app.get("/")
async def get_multikino_films():
    url = "https://www.multikino.pl/api/microservice/showings/cinemas/0011/films"
    
    proxy_url = os.getenv("PROXY_URL")
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    async with AsyncSession(
        impersonate="chrome120", 
        headers=MULTIKINO_HEADERS, 
        timeout=15.0,
        proxies=proxies
    ) as client:
        try:
            await client.get("https://multikino.pl/")

            response = await client.get(url)
            
            if response.status_code != 200:
                error_text = response.text[:200]
                raise HTTPException(status_code=response.status_code, detail=f"Multikino odrzuciło zapytanie (KOD {response.status_code}). Odpowiedź: {error_text}")
                
            data = response.json()
            
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
        except RequestsError as exc:
            raise HTTPException(status_code=500, detail=f"Błąd połączenia z API: {exc}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Błąd parsowania danych: {str(e)}")