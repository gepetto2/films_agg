from datetime import datetime
from zoneinfo import ZoneInfo

def parse_start_time(start_time_raw: str) -> str:
    """Parsuje ciąg daty i w razie braku strefy czasowej dodaje Europe/Warsaw."""
    if not start_time_raw:
        return ""
    try:
        dt_obj = datetime.fromisoformat(start_time_raw)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
        return dt_obj.isoformat()
    except ValueError:
        return start_time_raw

def merge_release_year(existing_year, new_year):
    """Zwraca wcześniejszy z podanych lat premiery."""
    if existing_year and new_year:
        # Sprawdza, czy oba to liczby przed min() w celu uniknięcia błędów
        if str(existing_year).isdigit() and str(new_year).isdigit():
            return str(min(int(existing_year), int(new_year)))
        return str(min(str(existing_year), str(new_year)))
    elif existing_year:
        return str(existing_year)
    elif new_year:
        return str(new_year)
        
    return None
