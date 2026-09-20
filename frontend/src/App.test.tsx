import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";

function stubFetch(impl: () => Promise<Response>) {
  const fetchMock = vi.fn(impl);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(body: unknown, status: number) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

test("shows a loading state while the health check is pending", () => {
  stubFetch(() => new Promise(() => {}));

  render(<App />);

  expect(screen.getByRole("status")).toHaveTextContent("Checking backend");
});

test("shows the backend as healthy when the health check succeeds", async () => {
  const fetchMock = stubFetch(() =>
    jsonResponse({ status: "ok", db: true, pgvector: true }, 200),
  );

  render(<App />);

  expect(await screen.findByText("Backend healthy")).toBeInTheDocument();
  expect(screen.getByText("Database: ok")).toBeInTheDocument();
  expect(screen.getByText("pgvector: ok")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/health/", expect.anything());
});

test("shows which check failed when the backend reports unhealthy", async () => {
  stubFetch(() => jsonResponse({ status: "error", db: true, pgvector: false }, 503));

  render(<App />);

  expect(await screen.findByText("Backend unhealthy")).toBeInTheDocument();
  expect(screen.getByText("Database: ok")).toBeInTheDocument();
  expect(screen.getByText("pgvector: down")).toBeInTheDocument();
});

test("shows an unreachable message when the request fails", async () => {
  stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

  render(<App />);

  expect(await screen.findByText("Could not reach the backend")).toBeInTheDocument();
});

test("shows an unreachable message when the response is not the health JSON", async () => {
  stubFetch(() => Promise.resolve(new Response("<html>Bad Gateway</html>", { status: 502 })));

  render(<App />);

  expect(await screen.findByText("Could not reach the backend")).toBeInTheDocument();
});
