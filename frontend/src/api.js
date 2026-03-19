const BASE = '/api';

export async function fetchDashboardStocks() {
  const res = await fetch(`${BASE}/dashboard/stocks`);
  if (!res.ok) throw new Error('Failed to fetch dashboard stocks');
  return res.json();
}

export async function fetchStock(ticker) {
  const res = await fetch(`${BASE}/stock/${encodeURIComponent(ticker)}`);
  if (!res.ok) throw new Error(`Failed to fetch ${ticker}`);
  return res.json();
}

export async function fetchHealth() {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}
