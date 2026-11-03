import { useQuery } from "@tanstack/react-query";

const POLL_INTERVAL_MS = 5_000;

type Readiness = { database: boolean; redis: boolean };

async function fetchReadiness(): Promise<Readiness> {
  const response = await fetch("/readyz");
  return (await response.json()) as Readiness;
}

// Pantalla provisional: carga y consulta llegan en los hitos M2 y M3.
export function App() {
  const { data, isError } = useQuery({
    queryKey: ["readiness"],
    queryFn: fetchReadiness,
    refetchInterval: POLL_INTERVAL_MS,
  });

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", margin: "2rem auto", maxWidth: 640 }}>
      <h1>NorteLegal</h1>
      {isError && <p role="alert">No se pudo contactar con la API.</p>}
      {data && (
        <ul>
          <li>Base de datos: {data.database ? "disponible" : "no disponible"}</li>
          <li>Cola: {data.redis ? "disponible" : "no disponible"}</li>
        </ul>
      )}
    </main>
  );
}
