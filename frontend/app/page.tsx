"use client";

import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";

type Showing = {
  time: string;
  screen: string;
  cinemaName: string;
  franchise: string;
};

type Film = {
  title: string;
  movieType: string | null;
  showingsByDate: Record<string, Showing[]>;
};

// Typ dla surowych danych zwracanych z relacyjnej bazy Supabase
type RawMovieResponse = {
  title: string;
  movie_type: string | null;
  screenings: {
    start_time: string;
    room_name: string;
    cinemas: {
      name: string;
      franchise: string | null;
    } | null;
  }[];
};

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const supabase = createClient(supabaseUrl, supabaseKey);

// Konfiguracja kolorów dla poszczególnych sieci kin
const FRANCHISE_STYLES: Record<string, { card: string; text: string }> = {
  "Multikino": {
    card: "border-[rgb(226,0,122)] dark:border-[rgba(226,0,122,0.8)] bg-[rgba(226,0,122,0.1)] dark:bg-[rgba(226,0,122,0.2)]",
    text: "text-[rgb(226,0,122)] dark:text-[rgba(226,0,122,0.8)]",
  },
  "Cinema City": {
    card: "border-[rgb(245,130,30)] dark:border-[rgba(245,130,30,0.8)] bg-[rgba(245,130,30,0.1)] dark:bg-[rgba(245,130,30,0.2)]",
    text: "text-[rgb(245,130,30)] dark:text-[rgba(245,130,30,0.8)]",
  },
  "default": {
    card: "border-[#0088FF] dark:border-[#33A1FF] bg-[#0088FF]/10 dark:bg-[#0088FF]/20",
    text: "text-[#0088FF] dark:text-[#33A1FF]",
  },
};

function FilmCard({ film }: { film: Film }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedDays, setExpandedDays] = useState<Record<string, boolean>>({});

  const toggleDay = (date: string) => {
    setExpandedDays((prev) => ({
      ...prev,
      [date]: !prev[date],
    }));
  };

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex justify-between items-center text-left focus:outline-none"
      >
        <h2 className="text-2xl font-semibold text-gray-800 dark:text-gray-100">{film.title}</h2>
        <span className="text-gray-400 dark:text-gray-500 text-xl ml-4">
          {isExpanded ? "▲" : "▼"}
        </span>
      </button>
      
      {isExpanded && (
        <div className="mt-6 space-y-4">
          {Object.entries(film.showingsByDate).map(([date, dailyShowings]) => {
            const isDayExpanded = expandedDays[date];
            return (
              <div key={date} className="border border-gray-100 dark:border-gray-700 rounded-xl overflow-hidden">
                <button
                  onClick={() => toggleDay(date)}
                  className="w-full flex justify-between items-center p-4 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 text-left focus:outline-none transition-colors"
                >
                  <h3 className="text-lg font-medium text-gray-800 dark:text-gray-200">{date}</h3>
                  <span className="text-gray-400 dark:text-gray-500">
                    {isDayExpanded ? "▲" : "▼"}
                  </span>
                </button>
                
                {isDayExpanded && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 p-4 bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-700">
                    {dailyShowings.map((showing, idx) => {
                      const style = FRANCHISE_STYLES[showing.franchise] || FRANCHISE_STYLES["default"];
                      return (
                        <div 
                          key={idx} 
                          className={`p-4 border-2 rounded-xl hover:shadow-md transition ${style.card}`}
                        >
                          <p className={`font-bold text-xl ${style.text}`}>
                            {showing.time}
                          </p>
                          <div className="text-sm font-medium text-gray-700 dark:text-gray-300 mt-1">
                            <p>{showing.screen}</p>
                            <p>{showing.cinemaName}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function Home() {
  const [films, setFilms] = useState<Film[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchFilms = async () => {
      try {
        // Pobieranie filmów wraz ze zagnieżdżonymi seansami z Supabase
        const { data, error } = await supabase
          .from("movies")
          .select<any, RawMovieResponse>(`
            title,
            movie_type,
            screenings (
              start_time,
              room_name,
              cinemas (
                name,
                franchise
              )
            )
          `);

        if (error) throw error;

        const formattedFilms: Film[] = (data || []).map((movie) => {
          // Optymalizacja: Grupowanie seansów po datach przy budowie stanu a nie podczas renderowania komponentu
          const showingsByDate: Record<string, Showing[]> = {};
          
          (movie.screenings || []).forEach((screening) => {
            const dateObj = new Date(screening.start_time);
            const dateKey = dateObj.toLocaleDateString("pl-PL");
            const timeKey = dateObj.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
            
            if (!showingsByDate[dateKey]) showingsByDate[dateKey] = [];
            
            showingsByDate[dateKey].push({
              time: timeKey,
              cinemaName: screening.cinemas?.name ?? "Brak informacji",
              screen: screening.room_name || "Brak informacji",
              franchise: screening.cinemas?.franchise ?? "Nieznane",
            });
          });

          // Sortowanie seansów czasowo w obrębie danego dnia (tylko raz)
          Object.values(showingsByDate).forEach((showings) => {
            showings.sort((a, b) => a.time.localeCompare(b.time));
          });

          return {
            title: movie.title,
            movieType: movie.movie_type,
            showingsByDate,
          };
        });

        setFilms(formattedFilms);
      } catch (err: any) {
        setError(err.message || "Wystąpił błąd podczas pobierania danych z Supabase");
      } finally {
        setLoading(false);
      }
    };

    fetchFilms();
  }, []);

  const regularFilms = films.filter((f) => !f.movieType);
  const specialFilms = films.filter((f) => f.movieType);

  const specialEventsGrouped = specialFilms.reduce((acc, film) => {
    const type = film.movieType!;
    if (!acc[type]) {
      acc[type] = [];
    }
    acc[type].push(film);
    return acc;
  }, {} as Record<string, Film[]>);

  return (
    <main className="min-h-screen p-4 md:p-8 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-4xl font-bold mb-8 text-center text-blue-600 dark:text-blue-400">Repertuar kin</h1>
        
        {loading ? (
          <div className="flex justify-center items-center py-24 text-xl text-gray-700 dark:text-gray-200">Ładowanie repertuaru...</div>
        ) : error ? (
          <div className="flex justify-center items-center py-24 text-xl text-red-500">Błąd: {error}</div>
        ) : films.length === 0 ? (
          <p className="text-center text-lg py-24">Brak seansów do wyświetlenia.</p>
        ) : (
          <>
            {regularFilms.length > 0 && (
              <div className="space-y-8">
                {regularFilms.map(film => <FilmCard key={film.title} film={film} />)}
              </div>
            )}

            {Object.keys(specialEventsGrouped).length > 0 && (
              <div className="mt-16">
                <h1 className="text-4xl font-bold mb-8 text-center text-purple-600 dark:text-purple-400">Wydarzenia specjalne</h1>
                {Object.entries(specialEventsGrouped).map(([type, typeFilms]) => (
                  <div key={type} className="mb-12">
                    <h2 className="text-2xl font-semibold mb-6 text-gray-700 dark:text-gray-300 border-b pb-2 border-gray-200 dark:border-gray-700">
                      {type}
                    </h2>
                    <div className="space-y-8">
                      {typeFilms.map(film => <FilmCard key={film.title} film={film} />)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
