"use client";
import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  ColorType,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
export type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};
export function Candles({
  data,
  label = "Daily OHLC candlestick chart",
}: {
  data: Candle[];
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      height: 330,
      layout: {
        background: { type: ColorType.Solid, color: "#101b26" },
        textColor: "#8fa3b7",
      },
      grid: {
        vertLines: { color: "#1a2b3b" },
        horzLines: { color: "#1a2b3b" },
      },
      rightPriceScale: { borderColor: "#2b3c4d" },
      timeScale: { borderColor: "#2b3c4d" },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#55d6b0",
      downColor: "#f48088",
      borderVisible: false,
      wickUpColor: "#55d6b0",
      wickDownColor: "#f48088",
    });
    series.setData(data.map((r) => ({ ...r, time: r.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);
  return (
    <div
      role="img"
      aria-label={label}
      ref={ref}
      style={{ height: 330, width: "100%" }}
    />
  );
}
export function SeriesChart({
  data,
  field,
  color = "#55d6b0",
  numeric = false,
}: {
  data: Record<string, number | null>[];
  field: string;
  color?: string;
  numeric?: boolean;
}) {
  return (
    <div
      style={{ height: 220, width: "100%" }}
      role="img"
      aria-label={field + " chart"}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id={"fill-" + field} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#22303d" vertical={false} />
          <XAxis
            dataKey="time"
            tickFormatter={(t) =>
              new Date(t * 1000).toLocaleDateString("en", {
                month: "short",
                day: "numeric",
              })
            }
            minTickGap={60}
            stroke="#8092a4"
            fontSize={10}
          />
          <YAxis
            tickFormatter={(n) =>
              numeric || field === "correlation"
                ? Number(n).toFixed(1)
                : (n * 100).toFixed(0) + "%"
            }
            stroke="#8092a4"
            fontSize={10}
          />
          <Tooltip
            contentStyle={{
              background: "#14212d",
              border: "1px solid #2a3c4d",
            }}
            labelFormatter={(t) =>
              new Date(Number(t) * 1000).toLocaleDateString()
            }
            formatter={(v) =>
              numeric || field === "correlation"
                ? Number(v).toFixed(2)
                : (Number(v) * 100).toFixed(2) + "%"
            }
          />
          <Area
            type="monotone"
            dataKey={field}
            stroke={color}
            fill={"url(#fill-" + field + ")"}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
