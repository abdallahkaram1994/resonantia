import { useEffect, useState } from "react";

type Health = { db: boolean; pgvector: boolean };

type State =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "failed"; health: Health | null };

function isHealth(value: unknown): value is Health {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Health).db === "boolean" &&
    typeof (value as Health).pgvector === "boolean"
  );
}

async function fetchHealth(signal: AbortSignal): Promise<State> {
  const response = await fetch("/api/health/", { signal });
  const body: unknown = await response.json();
  if (!isHealth(body)) {
    return { kind: "failed", health: null };
  }
  return { kind: response.ok ? "ok" : "failed", health: body };
}

function Check({ label, ok }: { label: string; ok: boolean }) {
  return (
    <li>
      {label}: {ok ? "ok" : "down"}
    </li>
  );
}

export default function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then(setState)
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ kind: "failed", health: null });
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold">Resonantia</h1>
      <p className="text-sm text-gray-500">Scaffold placeholder</p>
      <section role="status" className="rounded-lg border border-gray-300 p-4 text-sm">
        {state.kind === "loading" && <p>Checking backend…</p>}
        {state.kind === "ok" && (
          <>
            <p className="font-medium text-green-700">Backend healthy</p>
            <ul>
              <Check label="Database" ok={state.health.db} />
              <Check label="pgvector" ok={state.health.pgvector} />
            </ul>
          </>
        )}
        {state.kind === "failed" && (
          <>
            <p className="font-medium text-red-700">
              {state.health ? "Backend unhealthy" : "Could not reach the backend"}
            </p>
            {state.health && (
              <ul>
                <Check label="Database" ok={state.health.db} />
                <Check label="pgvector" ok={state.health.pgvector} />
              </ul>
            )}
          </>
        )}
      </section>
    </main>
  );
}
