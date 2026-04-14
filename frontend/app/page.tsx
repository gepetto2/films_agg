"use client";

import { useEffect, useState } from "react";

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

export default function Home() {
  const [films, setFilms] = useState<Film[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    
    fetch(apiUrl)
      .then((res) => {
        if (!res.ok) throw new Error(`Błąd serwera: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setFilms(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

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
                <h2 className="text-2xl font-semibold mb-6 text-gray-800 dark:text-gray-100">{film.title}</h2>
                
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {film.showings.map((showing, idx) => (
                    <div key={idx} className="p-4 border border-gray-200 dark:border-gray-700 rounded-xl bg-gray-50 dark:bg-gray-900 hover:shadow-md transition">
                      <p className="font-bold text-xl text-blue-500">{showing.time}</p>
                      <p className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">{showing.date}</p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
