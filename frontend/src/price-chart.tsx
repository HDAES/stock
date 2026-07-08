import { useEffect, useRef } from "react";
import {
  CandlestickData,
  CandlestickSeries,
  createChart,
  HistogramData,
  HistogramSeries,
  Time
} from "lightweight-charts";
import type { KlinePoint } from "./types";

export function KlineChart({ data }: { data: KlinePoint[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      height: 420,
      layout: {
        background: { color: "#ffffff" },
        textColor: "#475569"
      },
      grid: {
        vertLines: { color: "#e2e8f0" },
        horzLines: { color: "#e2e8f0" }
      },
      rightPriceScale: {
        borderColor: "#cbd5e1"
      },
      timeScale: {
        borderColor: "#cbd5e1",
        timeVisible: false
      }
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#0f766e",
      downColor: "#dc2626",
      borderVisible: false,
      wickUpColor: "#0f766e",
      wickDownColor: "#dc2626"
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "#94a3b8"
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0
      }
    });

    const candleData: CandlestickData<Time>[] = data
      .filter((point) => point.open !== null && point.high !== null && point.low !== null && point.close !== null)
      .map((point) => ({
        time: point.date as Time,
        open: point.open!,
        high: point.high!,
        low: point.low!,
        close: point.close!
      }));

    const volumeData: HistogramData<Time>[] = data
      .filter((point) => point.volume !== null && point.close !== null && point.open !== null)
      .map((point) => ({
        time: point.date as Time,
        value: point.volume!,
        color: point.close! >= point.open! ? "rgba(15, 118, 110, 0.35)" : "rgba(220, 38, 38, 0.3)"
      }));

    candles.setData(candleData);
    volume.setData(volumeData);
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [data]);

  return <div ref={containerRef} className="kline-chart" />;
}
