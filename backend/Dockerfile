# 1. Używamy lekkiego obrazu Pythona
FROM python:3.11-slim

# 2. Ustawiamy folder roboczy wewnątrz kontenera
WORKDIR /app

# 3. Kopiujemy listę bibliotek i instalujemy je
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Kopiujemy resztę kodu (main.py)
COPY . .

# 5. Informujemy, na jakim porcie działa aplikacja
EXPOSE 8000

# 6. Komenda startowa
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]