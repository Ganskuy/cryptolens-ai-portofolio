"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  ChevronRight,
  Compass,
  Layers,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Star,
  X,
} from "lucide-react";
import { z } from "zod";
import { Candles, SeriesChart, type Candle } from "../components/charts";
import { money, pct } from "./utils";
import {
  api,
  ApiError,
  MetadataHistory,
  csrfHeaders,
  AccountBoundary,
  Universe,
  DefiResearch,
  ResearchNotes,
  TechnicalResearch,
} from "../components/research";
const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (attempt, error) =>
        !(error instanceof ApiError && error.status < 500) && attempt < 2,
    },
  },
});
const AssetSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  name: z.string(),
  stablecoin: z.boolean(),
  price: z.string().nullable(),
  source: z.string().nullable(),
  bid_ask: z
    .object({
      spread_bps: z.number(),
      quote: z.string(),
      observed_at: z.string(),
    })
    .nullable()
    .optional(),
  observed_at: z.string().nullable(),
  stale: z.boolean(),
  market_cap: z.union([z.string(), z.number()]).nullable().optional(),
  total_volume: z.union([z.string(), z.number()]).nullable().optional(),
  price_change_percentage_24h: z.number().nullable().optional(),
});
type Risk = {
  asset_id: string;
  dataset_id: string;
  source: string;
  eligible: boolean;
  coverage: number;
  annualized_volatility?: number;
  max_drawdown?: number;
  cumulative_return?: number;
  var_95?: number;
  sharpe?: number;
  sortino?: number;
  series: Record<string, number>[];
  rolling?: Record<string, number>[];
  return_distribution?: { lower: number; upper: number; count: number }[];
};
type Ranking = {
  rankings: (Risk & { score: number })[];
  excluded: { asset_id: string; reason: string }[];
  methodology: string;
  score_units: string;
};
type Answer = {
  charts?: {
    type: string;
    metric: string;
    dataset_id: string;
    asset_id: string;
  }[];
  answer: string;
  key_findings: { field: string; value: unknown; evidence_id: string }[];
  evidence: Record<string, unknown>;
  limitations: string[];
  model: string;
};
function Status({ children }: { children: React.ReactNode }) {
  return <span className="badge">{children}</span>;
}
function Dashboard() {
  const [tab, setTab] = useState("Market Overview"),
    [selected, setSelected] = useState("bitcoin"),
    [days, setDays] = useState(90),
    [search, setSearch] = useState(""),
    [sort, setSort] = useState("cap"),
    [watch, setWatch] = useState<string[]>([]),
    [onlyWatch, setOnlyWatch] = useState(false),
    [compare, setCompare] = useState<string[]>(["bitcoin", "ethereum"]),
    [weight, setWeight] = useState(0.5),
    [preset, setPreset] = useState("balanced"),
    [riskFree, setRiskFree] = useState(""),
    [streamText, setStreamText] = useState(""),
    [prompt, setPrompt] = useState(""),
    [stage, setStage] = useState(""),
    [answer, setAnswer] = useState<Answer | null>(null),
    [error, setError] = useState(""),
    [session, setSession] = useState<string | undefined>(),
    [busy, setBusy] = useState(false),
    [ticks, setTicks] = useState<
      Record<string, { price: string; observed_at: number }>
    >({}),
    [connected, setConnected] = useState(false);
  const configuration = useQuery({
    queryKey: ["config"],
    queryFn: () => api<{ market_ws_url: string }>("/config"),
  });
  const abort = useRef<AbortController | null>(null);
  const market = useQuery({
    queryKey: ["market"],
    queryFn: async () => {
      const d = await api<{
        assets: unknown[];
        mode: string;
        global: {
          data: {
            total_market_cap: { usd: number };
            total_volume: { usd: number };
            market_cap_percentage: { btc: number };
          };
        } | null;
        snapshot_at: string;
      }>("/market/overview");
      return { ...d, assets: z.array(AssetSchema).parse(d.assets) };
    },
    refetchInterval: 15000,
  });
  const risk = useQuery({
    queryKey: ["risk", selected, days],
    queryFn: () =>
      api<Risk>(`/analytics/risk?asset_id=${selected}&days=${days}`),
    refetchInterval: 60000,
  });
  const candles = useQuery({
    queryKey: ["candles", selected, days],
    queryFn: () =>
      api<{ candles: Candle[] }>(`/assets/${selected}/candles?days=${days}`),
    refetchInterval: 60000,
  });
  const fundamentals = useQuery({
    queryKey: ["fundamentals", selected],
    queryFn: () =>
      api<Record<string, unknown>>(`/assets/${selected}/fundamentals`),
    enabled: tab === "Asset Detail",
  });
  const ranks = useQuery({
    queryKey: ["rankings", days, weight, preset, riskFree],
    queryFn: () =>
      api<Ranking>(
        `/analytics/rankings?days=${days}&volatility_weight=${weight}&preset=${preset}${riskFree !== "" ? `&risk_free=${Number(riskFree) / 100}` : ""}`,
      ),
    enabled: tab === "Risk Analytics",
  });
  const comparison = useQuery({
    queryKey: ["compare", compare, days],
    queryFn: () =>
      api<{
        results: Risk[];
        correlation: {
          rolling: Record<string, number>[];
          rolling_pair: string[];
          assets: string[];
          matrix: (number | null)[][];
          observations: number;
        };
      }>("/analytics/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ asset_ids: compare, days }),
      }),
    enabled: tab === "Risk Analytics" && compare.length >= 2,
  });
  const sessions = useQuery({
    queryKey: ["sessions", session, busy],
    queryFn: () =>
      api<{ sessions: { id: string; created_at: string }[] }>("/ai/sessions"),
    enabled: tab === "AI Analyst",
  });
  useEffect(() => {
    try {
      setWatch(JSON.parse(localStorage.getItem("cryptolens-watch") || "[]"));
    } catch {}
  }, []);
  useEffect(() => {
    if (!configuration.data) return;
    const socketUrl = new URL(configuration.data.market_ws_url, location.href);
    socketUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    let socket: WebSocket;
    let timer: ReturnType<typeof setTimeout>;
    let closed = false;
    function connect() {
      socket = new WebSocket(socketUrl.href);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          setTicks(
            Object.fromEntries(
              d.ticks.map(
                (r: {
                  asset_id: string;
                  price: string;
                  observed_at: number;
                }) => [r.asset_id, r],
              ),
            ),
          );
        } catch {}
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, 5000);
      };
      socket.onerror = () => socket.close();
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [configuration.data]);
  const assets = market.data?.assets || [],
    active = assets.find((a) => a.id === selected),
    global = market.data?.global?.data;
  const filtered = assets
    .filter(
      (a) =>
        (a.name + " " + a.symbol)
          .toLowerCase()
          .includes(search.toLowerCase()) &&
        (!onlyWatch || watch.includes(a.id)),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : sort === "change"
          ? (b.price_change_percentage_24h || 0) -
            (a.price_change_percentage_24h || 0)
          : Number(b.market_cap || 0) - Number(a.market_cap || 0),
    );
  function toggleWatch(id: string) {
    const next = watch.includes(id)
      ? watch.filter((a) => a !== id)
      : [...watch, id];
    setWatch(next);
    localStorage.setItem("cryptolens-watch", JSON.stringify(next));
  }
  async function send() {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setError("");
    setAnswer(null);
    setStreamText("");
    setStage("Connecting");
    abort.current = new AbortController();
    try {
      const response = await fetch("/api/v1/ai/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          message: prompt,
          session_id: session,
          request_id: crypto.randomUUID(),
        }),
        signal: abort.current.signal,
      });
      if (!response.ok) {
        const d = await response.json();
        throw new Error(d.detail || d.error || "AI unavailable");
      }
      const reader = response.body!.getReader(),
        decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const event of events) {
          if (!event.startsWith("data: ")) continue;
          const data = JSON.parse(event.slice(6));
          setStage(data.stage.replaceAll("_", " "));
          setSession(data.session_id);
          if (data.chunk) setStreamText((text) => text + data.chunk);
          if (data.result) setAnswer(data.result);
          if (data.error) setError(data.error);
        }
      }
    } catch (e) {
      setError(
        e instanceof Error && e.name === "AbortError"
          ? "Request cancelled. Reserved usage remains counted."
          : String(e),
      );
    } finally {
      setBusy(false);
    }
  }
  const navigation = [
    { name: "Market Overview", icon: Layers },
    { name: "Asset Explorer", icon: Compass },
    { name: "Asset Detail", icon: BarChart3 },
    { name: "Risk Analytics", icon: ShieldCheck },
    { name: "AI Analyst", icon: Sparkles },
    { name: "DeFi Research", icon: Layers },
  ];
  const marketTable = (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Asset</th>
            <th>Price · USD</th>
            <th>24h change</th>
            <th>Market cap</th>
            <th>Volume · USD</th>
            <th>Data status</th>
            <th>
              <span className="sr-only">Watchlist</span>☆
            </th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((a) => (
            <tr key={a.id}>
              <td>
                <button
                  className="asset-button"
                  onClick={() => {
                    setSelected(a.id);
                    setTab("Asset Detail");
                  }}
                >
                  <span
                    aria-hidden="true"
                    className={"coin coin-" + a.symbol.toLowerCase()}
                  >
                    {a.symbol.slice(0, 1)}
                  </span>
                  <span>
                    <strong>{a.name}</strong>
                    <small>
                      {a.symbol}
                      {a.stablecoin ? " · stablecoin" : ""}
                    </small>
                  </span>
                </button>
              </td>
              <td className="mono">{money(a.price)}</td>
              <td
                className={
                  (a.price_change_percentage_24h || 0) >= 0
                    ? "positive"
                    : "negative"
                }
              >
                {a.price_change_percentage_24h == null
                  ? "—"
                  : pct(a.price_change_percentage_24h / 100)}
              </td>
              <td>{money(a.market_cap, true)}</td>
              <td>{money(a.total_volume, true)}</td>
              <td>
                <span className={a.stale ? "muted" : "positive"}>
                  {a.stale ? "Delayed / fixture" : "● Updated"}
                </span>
              </td>
              <td>
                <button
                  aria-label={"Watch " + a.name}
                  className="icon-button"
                  onClick={() => toggleWatch(a.id)}
                >
                  <Star
                    size={16}
                    fill={watch.includes(a.id) ? "#f4ce7c" : "none"}
                  />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!filtered.length && (
        <div className="empty">No assets match this filter.</div>
      )}
    </div>
  );
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-mark">
            <Activity size={24} />
          </span>
          CryptoLens<span className="ai-label">AI</span>
        </Link>
        <div className="nav-caption">WORKSPACE</div>
        <nav>
          {navigation.map((n) => (
            <button
              key={n.name}
              className={tab === n.name ? "active" : ""}
              onClick={() => setTab(n.name)}
            >
              <n.icon size={18} />
              {n.name}
              {tab === n.name && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={20} />
          <strong>Research with context</strong>
          <p>
            Transparent methods.
            <br />
            Traceable market data.
            <br />
            No trade execution.
          </p>
          <span className="badge">PERSONAL RESEARCH</span>
        </div>
        <div className="sidebar-footer">
          <span className="status-dot" />
          Local workspace <small>v1.0</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={13} /> <strong>{tab}</strong>
          </span>
          <div>
            <span className={"status-dot " + (!connected ? "offline" : "")} />
            {connected ? "Feed connected" : "Feed reconnecting"}
            <span className="avatar">CL</span>
          </div>
        </header>
        <div className="content">
          <div className="title-row">
            <div>
              <div className="eyebrow">CRYPTOCURRENCY INTELLIGENCE</div>
              <h1>{tab}</h1>
              <p className="subtitle">
                {tab === "AI Analyst"
                  ? "Ask better questions. Investigate with verifiable evidence."
                  : "A clearer view of the market. Every metric, in context."}
              </p>
            </div>
            <Status>
              {market.data?.mode === "fixture"
                ? "SYNTHETIC FIXTURE"
                : "PUBLIC MARKET DATA"}{" "}
              <ArrowUpRight size={13} />
            </Status>
          </div>
          {market.isPending && (
            <div className="skeleton">Loading provider snapshots…</div>
          )}
          {market.isError && (
            <div className="error">
              {market.error.message}
              <button onClick={() => market.refetch()}>Retry</button>
            </div>
          )}
          {market.data && (
            <div className="source-line">
              {market.data?.mode === "fixture"
                ? "Synthetic fixture data · Not live market values"
                : "CoinGecko USD snapshots · Binance USDT candles · UTC daily boundaries"}{" "}
              <span>
                Snapshot{" "}
                {new Date(market.data.snapshot_at).toLocaleTimeString()}
              </span>
            </div>
          )}
          {tab === "Market Overview" && (
            <>
              <div className="stats-grid">
                <Metric
                  title="GLOBAL MARKET CAP"
                  value={money(global?.total_market_cap.usd, true)}
                  note="CoinGecko aggregate"
                />
                <Metric
                  title="24H GLOBAL VOLUME"
                  value={money(global?.total_volume.usd, true)}
                  note="Reported trading volume"
                />
                <Metric
                  title="BITCOIN DOMINANCE"
                  value={
                    global
                      ? global.market_cap_percentage.btc.toFixed(2) + "%"
                      : "Unavailable"
                  }
                  note="Share of global market cap"
                />
                <Metric
                  title="RESEARCH UNIVERSE"
                  value={String(assets.length)}
                  note="Explicit provider identity mappings"
                />
              </div>
              <div className="overview-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>
                        Market trajectory{" "}
                        <span className="muted">
                          / {active?.symbol || "BTC"}
                        </span>
                      </h2>
                      <p>
                        {market.data?.mode === "fixture"
                          ? "Synthetic fixture candles"
                          : "Finalized daily candles · USDT"}
                      </p>
                    </div>
                    <select
                      aria-label="Chart asset"
                      value={selected}
                      onChange={(e) => setSelected(e.target.value)}
                    >
                      {assets.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.symbol}
                        </option>
                      ))}
                    </select>
                  </div>
                  {candles.data?.candles.length ? (
                    <Candles data={candles.data.candles} />
                  ) : (
                    <div className="empty">
                      Waiting for finalized provider candles
                    </div>
                  )}
                </section>
                <section className="panel market-pulse">
                  <div className="panel-heading">
                    <div>
                      <h2>Market pulse</h2>
                      <p>Largest moves in this universe</p>
                    </div>
                    <Activity size={18} />
                  </div>
                  {[...assets]
                    .sort(
                      (a, b) =>
                        Math.abs(b.price_change_percentage_24h || 0) -
                        Math.abs(a.price_change_percentage_24h || 0),
                    )
                    .slice(0, 5)
                    .map((a) => (
                      <button
                        className="pulse-row"
                        key={a.id}
                        onClick={() => {
                          setSelected(a.id);
                          setTab("Asset Detail");
                        }}
                      >
                        <span className="coin">{a.symbol[0]}</span>
                        <div>
                          <strong>{a.symbol}</strong>
                          <small>{a.name}</small>
                        </div>
                        <span
                          className={
                            (a.price_change_percentage_24h || 0) >= 0
                              ? "positive"
                              : "negative"
                          }
                        >
                          {a.price_change_percentage_24h == null
                            ? "—"
                            : pct(a.price_change_percentage_24h / 100)}
                        </span>
                      </button>
                    ))}
                  <p className="footnote">
                    Historical movement is descriptive. It does not indicate
                    future direction.
                  </p>
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Market watch</h2>
                    <p>Curated coverage, explicit provenance</p>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => setTab("Asset Explorer")}
                  >
                    Explore assets <ArrowUpRight size={14} />
                  </button>
                </div>
                {marketTable}
              </section>
            </>
          )}
          {tab === "Market Overview" && (
            <section className="panel">
              <div className="panel-heading">
                <h2>Market-cap composition · research universe</h2>
                <small>Excludes assets outside this registry</small>
              </div>
              <div className="composition">
                {assets
                  .filter((a) => Number(a.market_cap) > 0)
                  .map((a, i) => (
                    <div
                      key={a.id}
                      title={`${a.name}: ${money(a.market_cap, true)}`}
                      style={{
                        flex: Number(a.market_cap),
                        background: [
                          "#55d6b0",
                          "#9eacf7",
                          "#f4ce7c",
                          "#72a9dc",
                          "#d69ed3",
                        ][i % 5],
                      }}
                    />
                  ))}
              </div>
              <p className="footnote">
                {assets
                  .filter((a) => Number(a.market_cap) > 0)
                  .map((a) => a.symbol)
                  .join(" · ")}{" "}
                · CoinGecko reported market capitalization; fixture mode uses
                labeled synthetic values.
              </p>
            </section>
          )}
          {tab === "DeFi Research" && <DefiResearch />}
          {tab === "Asset Explorer" && (
            <Universe
              onSelect={(id) => {
                setSelected(id);
                setTab("Asset Detail");
              }}
            />
          )}
          {tab === "Asset Detail" && (
            <>
              <TechnicalResearch asset={selected} days={days} />
              <ResearchNotes asset={selected} />
              <MetadataHistory asset={selected} />
            </>
          )}
          {tab === "Asset Explorer" && (
            <section className="panel">
              <div className="panel-heading">
                <div className="search">
                  <Search size={16} />
                  <input
                    placeholder="Search name or symbol"
                    aria-label="Search assets"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <div className="controls">
                  <button
                    className={onlyWatch ? "selected" : ""}
                    onClick={() => setOnlyWatch(!onlyWatch)}
                  >
                    Watchlist
                  </button>
                  <select
                    aria-label="Sort assets"
                    value={sort}
                    onChange={(e) => setSort(e.target.value)}
                  >
                    <option value="cap">Market cap</option>
                    <option value="change">24h change</option>
                    <option value="name">Name</option>
                  </select>
                </div>
              </div>
              {marketTable}
            </section>
          )}
          {tab === "Asset Detail" && (
            <>
              <div className="detail-heading">
                <select
                  aria-label="Select asset"
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  {assets.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.symbol}
                    </option>
                  ))}
                </select>
                <div className="controls">
                  {[30, 90, 180, 365, 730, 1826].map((n) => (
                    <button
                      key={n}
                      className={days === n ? "selected" : ""}
                      onClick={() => setDays(n)}
                    >
                      {n}D
                    </button>
                  ))}
                </div>
              </div>
              <div className="stats-grid">
                <Metric
                  title="SNAPSHOT PRICE · USD"
                  value={money(active?.price)}
                  note={active?.source || "Unavailable"}
                />
                <Metric
                  title="LIVE PRICE · USDT"
                  value={
                    ticks[selected]
                      ? money(ticks[selected].price)
                      : "Unavailable"
                  }
                  note={
                    ticks[selected]
                      ? new Date(
                          ticks[selected].observed_at,
                        ).toLocaleTimeString()
                      : "No recent Binance tick"
                  }
                />
                <Metric
                  title="PERIOD RETURN"
                  value={pct(risk.data?.cumulative_return)}
                  note={`${days} daily return window`}
                />
                <Metric
                  title="ANNUALIZED VOLATILITY"
                  value={pct(risk.data?.annualized_volatility)}
                  note="Sample standard deviation × √365"
                />
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>{active?.name} · Daily price action</h2>
                  <Status>
                    {market.data?.mode === "fixture"
                      ? "SYNTHETIC FIXTURE"
                      : "BINANCE / USDT"}
                  </Status>
                </div>
                {candles.data?.candles.length ? (
                  <Candles data={candles.data.candles} />
                ) : (
                  <div className="empty">No finalized candles available</div>
                )}
              </section>
              <div className="two-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Historical drawdown</h2>
                    <span className="negative">
                      {pct(risk.data?.max_drawdown)}
                    </span>
                  </div>
                  <SeriesChart
                    data={risk.data?.series || []}
                    field="drawdown"
                    color="#f48088"
                  />
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Cumulative return</h2>
                  </div>
                  <SeriesChart
                    data={risk.data?.series || []}
                    field="cumulative_return"
                  />
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Available fundamentals</h2>
                  <Status>COINGECKO</Status>
                </div>
                <div className="stats-grid fundamentals">
                  <Metric
                    title="CIRCULATING SUPPLY"
                    value={
                      fundamentals.data?.circulating_supply
                        ? Number(
                            fundamentals.data.circulating_supply,
                          ).toLocaleString()
                        : "Unavailable"
                    }
                    note="Provider-reported token units"
                  />
                  <Metric
                    title="MAXIMUM SUPPLY"
                    value={
                      fundamentals.data?.max_supply
                        ? Number(fundamentals.data.max_supply).toLocaleString()
                        : "Unavailable"
                    }
                    note="Missing is not zero or unlimited"
                  />
                  <Metric
                    title="SUPPLY RATIO"
                    value={pct(
                      fundamentals.data?.supply_ratio as number | undefined,
                    )}
                    note="Circulating / maximum"
                  />
                  <Metric
                    title="VOLUME / MARKET CAP"
                    value={pct(
                      fundamentals.data?.volume_to_market_cap as
                        number | undefined,
                    )}
                    note="Reported daily turnover proxy"
                  />
                </div>
              </section>
              <div className="methodology">
                Dataset {risk.data?.dataset_id || "unavailable"} · Coverage{" "}
                {pct(risk.data?.coverage)} · Sharpe and Sortino remain
                unavailable unless an explicit risk-free assumption is supplied.
                Indicative bid-ask spread:{" "}
                {active?.bid_ask
                  ? active.bid_ask.spread_bps.toFixed(2) + " bps (USDT)"
                  : "unavailable"}
                . Last metadata observation:{" "}
                {active?.observed_at || "unavailable"}.
              </div>
            </>
          )}
          {tab === "Risk Analytics" && (
            <>
              <div className="methodology">
                <ShieldCheck size={18} />
                <span>
                  Historical risk, transparent scoring. Lower scores indicate
                  lower relative volatility and drawdown within this universe.
                  Stablecoins are excluded. This is not an investment
                  recommendation.
                </span>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Risk ranking</h2>
                    <p>
                      Preset: {preset} · lower sorting score ranks first ·
                      rank-v2
                    </p>
                  </div>
                  <div className="controls">
                    <select
                      aria-label="Ranking preset"
                      value={preset}
                      onChange={(e) => setPreset(e.target.value)}
                    >
                      {[
                        "balanced",
                        "volatility",
                        "drawdown",
                        "liquidity",
                        "sharpe",
                      ].map((p) => (
                        <option key={p}>{p}</option>
                      ))}
                    </select>
                    {preset === "sharpe" && (
                      <label>
                        Annual risk-free assumption (%)
                        <input
                          aria-label="Risk-free assumption"
                          type="number"
                          step="0.1"
                          min="0"
                          max="100"
                          value={riskFree}
                          onChange={(e) => setRiskFree(e.target.value)}
                        />
                      </label>
                    )}
                    <label>
                      Volatility weight{" "}
                      <input
                        aria-label="Volatility weight"
                        type="range"
                        min="0"
                        max="1"
                        step="0.1"
                        value={weight}
                        onChange={(e) => setWeight(Number(e.target.value))}
                      />
                      {pct(weight)}
                    </label>
                    <select
                      aria-label="Risk period"
                      value={days}
                      onChange={(e) => setDays(Number(e.target.value))}
                    >
                      {[30, 90, 180, 365, 730, 1826].map((n) => (
                        <option value={n} key={n}>
                          {n} days
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                {ranks.isPending ? (
                  <div className="empty">Calculating metrics…</div>
                ) : ranks.isError ? (
                  <div className="error">{ranks.error.message}</div>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Asset</th>
                          <th>Risk score ↓</th>
                          <th>Annualized volatility</th>
                          <th>Max drawdown</th>
                          <th>Period return</th>
                          <th>Coverage</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ranks.data?.rankings.map((r, i) => (
                          <tr key={r.asset_id}>
                            <td>
                              {i + 1}. {r.asset_id}
                            </td>
                            <td>
                              <div className="score">
                                <span
                                  style={{
                                    width:
                                      (preset === "balanced" ? r.score : 0) +
                                      "%",
                                  }}
                                />
                                {r.score.toLocaleString(undefined, {
                                  maximumFractionDigits: 4,
                                })}
                              </div>
                            </td>
                            <td>{pct(r.annualized_volatility)}</td>
                            <td className="negative">{pct(r.max_drawdown)}</td>
                            <td>{pct(r.cumulative_return)}</td>
                            <td>{pct(r.coverage)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="footnote">
                  {ranks.data?.methodology} {ranks.data?.score_units}.{" "}
                  {ranks.data?.excluded
                    .map((r) => `${r.asset_id}: ${r.reason}`)
                    .join(" · ")}
                </div>
              </section>
              <div className="two-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Correlation matrix</h2>
                      <p>
                        Aligned daily returns ·{" "}
                        {comparison.data?.correlation.observations || 0}{" "}
                        observations
                      </p>
                    </div>
                  </div>
                  <div className="chips">
                    {assets.map((a) => (
                      <button
                        className={compare.includes(a.id) ? "selected" : ""}
                        key={a.id}
                        onClick={() =>
                          setCompare(
                            compare.includes(a.id)
                              ? compare.filter((x) => x !== a.id)
                              : compare.length < 5
                                ? [...compare, a.id]
                                : compare,
                          )
                        }
                      >
                        {a.symbol}
                      </button>
                    ))}
                  </div>
                  {comparison.data && (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Asset</th>
                            {comparison.data.correlation.assets.map((a) => (
                              <th key={a}>
                                {assets.find((x) => x.id === a)?.symbol}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {comparison.data.correlation.matrix.map((row, i) => (
                            <tr key={i}>
                              <td>{comparison.data.correlation.assets[i]}</td>
                              {row.map((v, j) => (
                                <td
                                  key={j}
                                  style={{
                                    background: `rgba(85,214,176,${Math.abs(v || 0) * 0.25})`,
                                  }}
                                >
                                  {v?.toFixed(2) ?? "—"}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Rolling volatility · {selected}</h2>
                  </div>
                  <SeriesChart
                    data={risk.data?.rolling || []}
                    field="volatility"
                    color="#9eacf7"
                  />
                  <p className="footnote">
                    Thirty contiguous daily returns. Gaps are not interpolated.
                  </p>
                </section>
              </div>
            </>
          )}
          {tab === "Risk Analytics" && (
            <>
              <div className="two-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Daily return distribution · {selected}</h2>
                  </div>
                  <div
                    className="histogram"
                    role="img"
                    aria-label="Daily return distribution"
                  >
                    {risk.data?.return_distribution?.map((bin, i) => (
                      <div
                        key={i}
                        title={`${pct(bin.lower)} to ${pct(bin.upper)}: ${bin.count} observations`}
                      >
                        <span
                          style={{
                            height: `${(bin.count / Math.max(...(risk.data?.return_distribution || []).map((b) => b.count), 1)) * 130}px`,
                          }}
                        />
                        <small>{pct(bin.lower)}</small>
                      </div>
                    ))}
                  </div>
                  <p className="footnote">
                    Observed daily return counts. Hover a bin for its interval.
                  </p>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Rolling correlation</h2>
                    <small>
                      {comparison.data?.correlation.rolling_pair.join(" / ")}
                    </small>
                  </div>
                  <SeriesChart
                    data={comparison.data?.correlation.rolling || []}
                    field="correlation"
                    color="#9eacf7"
                  />
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Relative performance · selected assets</h2>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Asset</th>
                        <th>Cumulative return</th>
                        <th>Annualized volatility</th>
                        <th>Maximum drawdown</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.data?.results.map((r) => (
                        <tr key={r.asset_id}>
                          <td>{r.asset_id}</td>
                          <td>{pct(r.cumulative_return)}</td>
                          <td>{pct(r.annualized_volatility)}</td>
                          <td>{pct(r.max_drawdown)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
          {tab === "AI Analyst" && (
            <div className="chat-layout">
              <section className="panel chat">
                <div className="analyst-heading">
                  <span className="brand-mark">
                    <Sparkles size={26} />
                  </span>
                  <h2>Your research, grounded.</h2>
                  <p>
                    English or Bahasa Indonesia. Read-only analytics.
                    <br />
                    Numerical findings come directly from backend datasets.
                  </p>
                </div>
                <div className="suggestions">
                  {[
                    "Analyze Bitcoin historical risk",
                    "Bandingkan risiko Ethereum dan Solana",
                    "Rank assets by historical risk",
                  ].map((q) => (
                    <button key={q} onClick={() => setPrompt(q)}>
                      {q}
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
                {busy && (
                  <div className="activity" role="status">
                    <span className="status-dot" />
                    {stage}…
                  </div>
                )}
                {error && (
                  <div className="error" role="alert">
                    {error}
                    <button onClick={send}>Retry</button>
                  </div>
                )}
                {busy && streamText && <p aria-live="polite">{streamText}</p>}
                {answer && (
                  <article className="answer">
                    <Status>BACKEND-GROUNDED FINDINGS</Status>
                    <p>{answer.answer}</p>
                    <table>
                      <tbody>
                        {answer.key_findings.map((f, i) => (
                          <tr key={i}>
                            <td>{f.field.replaceAll("_", " ")}</td>
                            <td>{String(f.value)}</td>
                            <td>{f.evidence_id}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {answer.charts
                      ?.filter(
                        (c) =>
                          c.type === "line" && c.metric === "cumulative_return",
                      )
                      .map((c) => (
                        <EvidenceChart
                          key={c.dataset_id}
                          datasetId={c.dataset_id}
                        />
                      ))}
                    <details>
                      <summary>Sources & limitations</summary>
                      <p>{answer.limitations.join(" ")}</p>
                      <pre>{JSON.stringify(answer.evidence, null, 2)}</pre>
                      <small>Model: {answer.model}</small>
                    </details>
                  </article>
                )}
                <form
                  className="composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    send();
                  }}
                >
                  <textarea
                    aria-label="Ask the AI analyst"
                    placeholder="Ask about assets, historical risk, or market data…"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    maxLength={1500}
                  />
                  <div>
                    <span>{prompt.length}/1500 · No trading tools</span>
                    {busy ? (
                      <button
                        type="button"
                        onClick={() => abort.current?.abort()}
                      >
                        <X size={16} />
                        Cancel
                      </button>
                    ) : (
                      <button
                        type="submit"
                        className="primary"
                        disabled={!prompt.trim()}
                      >
                        <Send size={15} />
                        Analyze
                      </button>
                    )}
                  </div>
                </form>
                <p className="footnote">
                  AI interpretation may be wrong. Inspect the evidence and data
                  freshness before drawing conclusions.
                </p>
              </section>
              <section className="panel sessions">
                <div className="panel-heading">
                  <h2>Research history</h2>
                </div>
                <button
                  onClick={() => {
                    setSession(undefined);
                    setAnswer(null);
                    setError("");
                  }}
                >
                  + New session
                </button>
                {sessions.data?.sessions.map((s) => (
                  <div key={s.id}>
                    <button
                      onClick={async () => {
                        setSession(s.id);
                        const h = await api<{
                          messages: { role: string; data: Answer }[];
                        }>(`/ai/sessions/${s.id}`);
                        setAnswer(
                          h.messages
                            .filter((m) => m.role === "assistant")
                            .at(-1)?.data || null,
                        );
                      }}
                    >
                      {new Date(s.created_at).toLocaleString()}
                    </button>
                    <button
                      aria-label="Delete session"
                      onClick={async () => {
                        await api(`/ai/sessions/${s.id}`, {
                          method: "DELETE",
                        });
                        if (session === s.id) setSession(undefined);
                        sessions.refetch();
                      }}
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
                <p className="footnote">
                  Private to the signed-in account, or browser cookie in local
                  mode. Retained for up to thirty days.
                </p>
              </section>
            </div>
          )}
          <footer>
            CryptoLens AI{" "}
            <span>
              Research only · No investment guarantees · Sources may be delayed
            </span>
            <a href="/api/v1/health/ready" target="_blank" rel="noreferrer">
              API readiness ↗
            </a>
          </footer>
        </div>
      </main>
    </div>
  );
}
function EvidenceChart({ datasetId }: { datasetId: string }) {
  const data = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api<Risk>(`/datasets/${datasetId}`),
  });
  return data.data ? (
    <div>
      <h3>Verified cumulative return · {data.data.asset_id}</h3>
      <SeriesChart data={data.data.series} field="cumulative_return" />
    </div>
  ) : (
    <p>Loading verified chart dataset…</p>
  );
}
function Metric({
  title,
  value,
  note,
}: {
  title: string;
  value: string;
  note: string;
}) {
  return (
    <section className="metric">
      <div>{title}</div>
      <strong>{value}</strong>
      <small>{note}</small>
    </section>
  );
}
export default function Page() {
  return (
    <QueryClientProvider client={client}>
      <AccountBoundary>
        <Dashboard />
      </AccountBoundary>
    </QueryClientProvider>
  );
}
