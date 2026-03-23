import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchDashboardSnapshots, fetchDashboardStocks, fetchStock } from './api';

const POLL_MS = 15 * 60 * 1000; // 15 min

export function useDashboardStocks() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analysisReady, setAnalysisReady] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    setLoading(true);
    setAnalysisReady(false);
    try {
      // Phase 1: fast snapshots — render cards immediately
      const snaps = await fetchDashboardSnapshots();
      setData(snaps.stocks);
      setLoading(false);

      // Phase 2: full analysis — update in background
      const full = await fetchDashboardStocks();
      setData(full.stocks);
      setAnalysisReady(true);
      if (full.last_updated) {
        setLastUpdated(new Date(full.last_updated).toLocaleTimeString());
      } else {
        setLastUpdated(new Date().toLocaleTimeString());
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  return { data, loading, analysisReady, error, lastUpdated, refresh: load };
}

export function useStockLookup() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const lookup = useCallback(async (ticker) => {
    if (!ticker) return;
    try {
      setLoading(true);
      setError(null);
      const data = await fetchStock(ticker);
      setResult(data);
    } catch (e) {
      setError(e.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return { result, loading, error, lookup, clear };
}
