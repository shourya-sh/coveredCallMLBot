import { useState, useEffect, useCallback } from 'react';
import { fetchDashboardStocks, fetchStock } from './api';

const POLL_MS = 15 * 60 * 1000; // 15 min

export function useDashboardStocks() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const result = await fetchDashboardStocks();
      setData(result.stocks);
      // Show backend's last_updated timestamp (when data was actually scraped)
      if (result.last_updated) {
        setLastUpdated(new Date(result.last_updated).toLocaleTimeString());
      } else {
        setLastUpdated(new Date().toLocaleTimeString());
      }
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  return { data, loading, error, lastUpdated, refresh: load };
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
