"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Candles, SeriesChart, type Candle } from "./charts";

export function csrfHeaders(): Record<string, string> {
  const value = document.cookie
    .split("; ")
    .find((v) => v.startsWith("cryptolens_csrf="))
    ?.split("=")[1];
  return value ? { "X-CSRF-Token": decodeURIComponent(value) } : {};
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...init,
    headers: { ...csrfHeaders(), ...init?.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof error.detail === "string"
        ? error.detail
        : error.error || `Request failed (${response.status})`,
      response.status,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export function AccountBoundary({ children }: { children: React.ReactNode }) {
  const client = useQueryClient();
  const account = useQuery({
    queryKey: ["account"],
    queryFn: () =>
      api<{ mode: string; user: { username: string; role: string } | null }>(
        "/auth/me",
      ),
    retry: false,
    refetchInterval: 60000,
  });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (account.isPending) return <div className="empty">Opening workspace…</div>;
  if (account.isError)
    return (
      <div className="empty" role="alert">
        Workspace unavailable.{" "}
        <button onClick={() => account.refetch()}>Retry</button>
      </div>
    );
  if (account.data.mode === "required" && !account.data.user)
    return (
      <main className="content">
        <form
          className="panel login"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api("/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
              });
              setPassword("");
              client.clear();
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <h1>CryptoLens workspace</h1>
          <label>
            Username
            <input
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              autoComplete="current-password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy}>
            Sign in
          </button>
          {error && <p role="alert">{error}</p>}
          <p className="footnote">
            Accounts are provisioned by the local administrator.
          </p>
        </form>
      </main>
    );
  return (
    <>
      {account.data.user && (
        <div className="account-bar">
          {account.data.user.username} · {account.data.user.role}{" "}
          <button
            onClick={async () => {
              await api("/auth/logout", { method: "POST" });
              client.clear();
              await account.refetch();
            }}
          >
            Sign out
          </button>
        </div>
      )}
      {children}
    </>
  );
}
type UniverseItem = {
  id: string;
  name: string;
  symbol: string;
  current_price: number | null;
  stale: boolean;
  analytics_supported: boolean;
};
export function Universe({ onSelect }: { onSelect: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [top, setTop] = useState(0);
  const result = useQuery({
    queryKey: ["universe", search, offset],
    queryFn: () =>
      api<{
        items: UniverseItem[];
        total: number;
        coverage_limit: number;
        source: string;
      }>(
        `/universe?q=${encodeURIComponent(search)}&offset=${offset}&limit=500`,
      ),
  });
  const items = result.data?.items || [];
  const start = Math.max(0, Math.floor(top / 56) - 5);
  const visible = items.slice(start, start + 20);
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Provider universe</h2>
        <input
          aria-label="Search provider universe"
          placeholder="Search captured assets"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
            setTop(0);
          }}
        />
      </div>
      <p className="footnote">
        {result.data?.total ?? 0} captured assets · configured coverage up to{" "}
        {result.data?.coverage_limit ?? 0} · {result.data?.source}. Analytics
        require reviewed exchange mappings. Discovery coverage is not the entire
        market.
      </p>
      {result.isError && <p role="alert">{result.error.message}</p>}
      <div
        key={`${search}:${offset}`}
        className="universe-scroll"
        role="region"
        aria-label="Virtualized provider universe"
        tabIndex={0}
        onScroll={(e) => setTop(e.currentTarget.scrollTop)}
      >
        <div style={{ height: items.length * 56, position: "relative" }}>
          {visible.map((row, i) => (
            <div
              className="universe-row"
              key={row.id}
              style={{
                position: "absolute",
                top: (start + i) * 56,
                height: 56,
                width: "100%",
              }}
            >
              <span>
                {row.name} <small>{row.symbol.toUpperCase()}</small>
              </span>
              <span>
                {row.current_price == null
                  ? "Unavailable"
                  : `$${row.current_price.toLocaleString()}`}
              </span>
              <small>
                {row.stale ? "Delayed / fixture" : "Recent snapshot"}
              </small>
              <button
                disabled={!row.analytics_supported}
                onClick={() => onSelect(row.id)}
              >
                {row.analytics_supported ? "Analyze" : "Discovery only"}
              </button>
            </div>
          ))}
        </div>
        {!result.isPending && !items.length && <p>No captured assets match.</p>}
      </div>
      <div className="controls">
        <button
          disabled={!offset}
          onClick={() => {
            setOffset(offset - 500);
            setTop(0);
          }}
        >
          Previous
        </button>
        <span>
          {offset + 1}–{offset + items.length} of {result.data?.total || 0}
        </span>
        <button
          disabled={offset + 500 >= (result.data?.total || 0)}
          onClick={() => {
            setOffset(offset + 500);
            setTop(0);
          }}
        >
          Next
        </button>
      </div>
    </section>
  );
}
type Research = {
  status: string;
  sources: string[];
  dimensions: { risk: string; assessment: string }[];
};
export function ResearchNotes({ asset }: { asset: string }) {
  const query = useQuery({
    queryKey: ["research", asset],
    queryFn: () => api<Research>(`/research/${asset}`),
  });
  return (
    <section className="panel">
      <h2>Issuer and counterparty research</h2>
      <p>
        {query.data?.status ||
          (query.isError ? query.error.message : "Loading research…")}
      </p>
      {query.data?.dimensions.map((r) => (
        <p key={r.risk}>
          <strong>{r.risk}: </strong>
          {r.assessment}
        </p>
      ))}
      {query.data?.sources.map((url) => (
        <p key={url}>
          <a href={url} target="_blank" rel="noreferrer">
            Source: {new URL(url).hostname}
          </a>
        </p>
      ))}
    </section>
  );
}
export function DefiResearch() {
  const query = useQuery({
    queryKey: ["aave"],
    queryFn: () =>
      api<{
        fresh: boolean;
        tvl_to_market_cap: number | null;
        meaning: string;
        mapping_version: string;
      }>("/defi/aave"),
  });
  const tvl = useQuery({
    queryKey: ["defi"],
    queryFn: () =>
      api<{
        metrics: {
          id: string;
          scope: string;
          source: string;
          history?: { date: number; totalLiquidityUSD: number }[];
        }[];
      }>("/defi"),
  });
  return (
    <>
      <section className="panel">
        <h2>Aave protocol exploration</h2>
        <p>
          TVL / governance-token market cap:{" "}
          <strong>
            {query.data?.tvl_to_market_cap?.toFixed(3) ?? "Unavailable"}
          </strong>
        </p>
        <p>{query.data?.meaning}</p>
        <p className="footnote">
          {query.data?.mapping_version} ·{" "}
          {query.data?.fresh
            ? "Recent paired observations"
            : "Missing or stale paired observations; valuation withheld"}
        </p>
        {query.isError && <p role="alert">{query.error.message}</p>}
        <h3>Protocol TVL history · USD</h3>
        <SeriesChart
          data={(
            tvl.data?.metrics.find((m) => m.id === "protocol:aave")?.history ||
            []
          ).map((row) => ({ time: row.date, tvl_usd: row.totalLiquidityUSD }))}
          field="tvl_usd"
          numeric
        />
        <p className="footnote">
          Source:{" "}
          {tvl.data?.metrics.find((m) => m.id === "protocol:aave")?.source ||
            "Unavailable"}
          . Missing observations are not filled.
        </p>
        <details>
          <summary>Protocol and chain TVL observations</summary>
          <pre>
            {JSON.stringify(
              tvl.data || {
                status: tvl.isError ? tvl.error.message : "Loading",
              },
              null,
              2,
            )}
          </pre>
        </details>
      </section>
      <ResearchNotes asset="aave" />
    </>
  );
}
export function TechnicalResearch({
  asset,
  days,
}: {
  asset: string;
  days: number;
}) {
  const [interval, setInterval] = useState("1d");
  const [field, setField] = useState("rsi");
  const daily = useQuery({
    queryKey: ["indicators", asset, days],
    queryFn: () =>
      api<{ series: Record<string, number | null>[]; method: string }>(
        `/assets/${asset}/indicators?days=${days}`,
      ),
    refetchInterval: 60000,
  });
  const hourly = useQuery({
    queryKey: ["hourly", asset],
    queryFn: () =>
      api<{
        candles: Candle[];
        coverage: number;
        indicators: { series: Record<string, number | null>[]; method: string };
      }>(`/assets/${asset}/hourly?hours=72`),
    enabled: interval === "1h",
    refetchInterval: 60000,
  });
  const data = interval === "1h" ? hourly.data?.indicators : daily.data;
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Technical observations</h2>
        <div className="controls">
          <select
            aria-label="Technical interval"
            value={interval}
            onChange={(e) => setInterval(e.target.value)}
          >
            <option value="1d">Daily</option>
            <option value="1h">Hourly · 72 hours</option>
          </select>
          <select
            aria-label="Technical indicator"
            value={field}
            onChange={(e) => setField(e.target.value)}
          >
            {["rsi", "sma", "ema", "macd", "signal", "histogram"].map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </div>
      </div>
      {interval === "1h" && (
        <>
          <Candles
            data={hourly.data?.candles || []}
            label="Hourly OHLC candlestick chart"
          />
          <p>
            Contiguous hourly return coverage:{" "}
            {((hourly.data?.coverage || 0) * 100).toFixed(1)}%
          </p>
        </>
      )}
      {(daily.isError || hourly.isError) && (
        <p role="alert">Technical observations unavailable.</p>
      )}
      <SeriesChart data={data?.series || []} field={field} numeric />
      <p className="footnote">
        {data?.method} RSI is an index from 0 to 100; price indicators use USDT.
        Missing warm-up values remain gaps. Descriptive only; predictive
        validity is not established.
      </p>
    </section>
  );
}

export function MetadataHistory({ asset }: { asset: string }) {
  const query = useQuery({
    queryKey: ["metadata-history", asset],
    queryFn: () =>
      api<{
        rows: { observed_at: string; market_cap?: string | number | null }[];
        limitation: string;
      }>(`/assets/${asset}/metadata-history?days=90`),
  });
  return (
    <section className="panel">
      <h2>Captured metadata history</h2>
      <p className="footnote">
        {query.data?.limitation ||
          "History starts at the first successful capture."}
      </p>
      {query.data?.rows.length ? (
        <SeriesChart
          data={query.data.rows.map((row) => ({
            time: Date.parse(row.observed_at) / 1000,
            market_cap: row.market_cap == null ? null : Number(row.market_cap),
          }))}
          field="market_cap"
          numeric
        />
      ) : (
        <p>
          {query.isError
            ? query.error.message
            : "No captured observations available."}
        </p>
      )}
    </section>
  );
}
