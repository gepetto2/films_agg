"use client";

import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";

type Showing = {
  date: string;
  time: string;
  screen: string;
  version: string;
};

type Film = {
  title: string;
  showings: Showing[];
};

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const supabase = createClient(supabaseUrl, supabaseKey);

export default function Home() {
  const [films, setFilms] = useState<Film[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedFilms, setExpandedFilms] = useState<Record<number, boolean>>({});
  const [expandedDays, setExpandedDays] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const fetchFilms = async () => {
      try {
        // Pobieranie filmów wraz ze zagnieżdżonymi seansami z Supabase
        const { data, error } = await supabase
          .from("movies")
          .select(`
            title,
            screenings (
              start_time,
              room_name
            )
          `);

        if (error) throw error;

        const formattedFilms: Film[] = (data || []).map((movie: any) => ({
          title: movie.title,
          showings: (movie.screenings || []).map((screening: any) => {
            const dateObj = new Date(screening.start_time);
            return {
              date: dateObj.toLocaleDateString("pl-PL"),
              time: dateObj.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" }),
              screen: screening.room_name || "Brak informacji",
              version: "Standard", // Zastępcza wartość, gdyż brak tego pola w nowym schemacie bazy
            };
          }),
        }));

        setFilms(formattedFilms);
      } catch (err: any) {
        setError(err.message || "Wystąpił błąd podczas pobierania danych z Supabase");
      } finally {
        setLoading(false);
      }
    };

    fetchFilms();
  }, []);

  const toggleFilm = (index: number) => {
    setExpandedFilms((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  const toggleDay = (filmIndex: number, date: string) => {
    const key = `${filmIndex}-${date}`;
    setExpandedDays((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const groupShowingsByDate = (showings: Showing[]) => {
    return showings.reduce((acc, showing) => {
      if (!acc[showing.date]) {
        acc[showing.date] = [];
      }
      acc[showing.date].push(showing);
      return acc;
    }, {} as Record<string, Showing[]>);
  };

  if (loading) {
    return <div className="flex justify-center items-center min-h-screen text-xl text-gray-700 dark:text-gray-200">Ładowanie repertuaru...</div>;
  }

  if (error) {
    return <div className="flex justify-center items-center min-h-screen text-xl text-red-500">Błąd: {error}</div>;
  }

  return (
    <main className="min-h-screen p-4 md:p-8 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-4xl font-bold mb-8 text-center text-blue-600 dark:text-blue-400">Repertuar Multikina</h1>
        
        {films.length === 0 ? (
          <p className="text-center text-lg">Brak seansów do wyświetlenia.</p>
        ) : (
          <div className="space-y-8">
            {films.map((film, index) => (
              <div key={index} className="bg-white dark:bg-gray-800 p-6 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700">
                <button
                  onClick={() => toggleFilm(index)}
                  className="w-full flex justify-between items-center text-left focus:outline-none"
                >
                  <h2 className="text-2xl font-semibold text-gray-800 dark:text-gray-100">{film.title}</h2>
                  <span className="text-gray-400 dark:text-gray-500 text-xl ml-4">
                    {expandedFilms[index] ? "▲" : "▼"}
                  </span>
                </button>
                
                {expandedFilms[index] && (
                  <div className="mt-6 space-y-4">
                    {Object.entries(groupShowingsByDate(film.showings)).map(([date, dailyShowings]) => {
                      const dayKey = `${index}-${date}`;
                      const isDayExpanded = expandedDays[dayKey];
                      return (
                        <div key={date} className="border border-gray-100 dark:border-gray-700 rounded-xl overflow-hidden">
                          <button
                            onClick={() => toggleDay(index, date)}
                            className="w-full flex justify-between items-center p-4 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 text-left focus:outline-none transition-colors"
                          >
                            <h3 className="text-lg font-medium text-gray-800 dark:text-gray-200">{date}</h3>
                            <span className="text-gray-400 dark:text-gray-500">
                              {isDayExpanded ? "▲" : "▼"}
                            </span>
                          </button>
                          
                          {isDayExpanded && (
                            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 p-4 bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-700">
                              {dailyShowings.map((showing, idx) => (
                                <div key={idx} className="p-4 border border-gray-200 dark:border-gray-700 rounded-xl bg-gray-50 dark:bg-gray-800 hover:shadow-md transition">
                                  <p className="font-bold text-xl text-blue-500">{showing.time}</p>
                                  <div className="text-sm font-medium text-gray-600 dark:text-gray-400 mt-1">
                                    <p>{showing.version}</p>
                                    <p>{showing.screen}</p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
