from fastapi import FastAPI
import httpx

app = FastAPI()

@app.get("/")
async def get_multikino_films():
    url = "https://www.multikino.pl/api/microservice/showings/cinemas/0011/films"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()
        
        parsed_films = []
        for film in data.get("result", []):
            title = film.get("filmTitle")
            showings = []
            
            for group in film.get("showingGroups", []):
                # Zbieramy nazwę dnia (np. "Dzisiaj") lub konkretną datę, jeżeli brakuje prefixu
                date_name = group.get("datePrefix") or group.get("date", "").split("T")[0]
                
                for session in group.get("sessions", []):
                    # Filtrujemy atrybuty, by znaleźć informację o języku (np. NAPISY, DUBBING)
                    lang_attrs = [attr.get("name") for attr in session.get("attributes", []) if attr.get("attributeType") == "Language"]
                    version = lang_attrs[0] if lang_attrs else "Brak info"
                    
                    # Formatujemy czas (np. z "2026-04-13T17:35:00" wyciągamy "17:35")
                    time_str = session.get("startTime", "").split("T")[-1][:5]
                    showings.append({"date": date_name, "time": time_str, "screen": session.get("screenName"), "version": version})
            
            if showings:
                parsed_films.append({"title": title, "showings": showings})
                
        return parsed_films