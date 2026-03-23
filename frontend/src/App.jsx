import { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  ArrowDownRight,
  ArrowUpRight,
  Loader2,
  Minus,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useDashboardStocks, useStockLookup } from './hooks';
import StockDetail from './components/StockDetail';
import DashboardSkeleton from './components/DashboardSkeleton';
import './App.css';

export default function App() {
  const { data: stocks, loading, analysisReady, lastUpdated, refresh } = useDashboardStocks();
  const { result: detail, loading: detailLoading, lookup, clear } = useStockLookup();
  const [query, setQuery] = useState('');

  const rankedStocks = useMemo(() => {
    if (!stocks) return [];
    return [...stocks]
      .map((stock) => {
        const analysis = stock.analysis || null;
        const topStrategy = analysis?.top_strategy || null;
        const confidence = Number(analysis?.confidence || 0);
        const trendBoost = Number(stock.change_pct || 0) > 0 ? 2 : 0;
        const strategyBoost = topStrategy && topStrategy !== 'NO_TRADE' ? 8 : 0;

        return {
          ...stock,
          analysis: analysis || {},
          strategy: topStrategy,
          confidence,
          score: confidence * 100 + strategyBoost + trendBoost,
          executionPlan: analysis?.execution_plan || null,
        };
      })
      .sort((a, b) => b.score - a.score);
  }, [stocks]);

  const featured = rankedStocks[0] || null;
  const surrounding = rankedStocks.slice(1);

  const handleSearch = (event) => {
    event.preventDefault();
    const ticker = query.trim().toUpperCase();
    if (!ticker) return;
    lookup(ticker);
  };

  const handleCardClick = (ticker) => lookup(ticker);

  return (
    <div className="app strategy-app">
      <header className="strategy-header">
        <div className="brand-block">
          <p className="brand-kicker">Live Options Radar</p>
          <h1>Dashy Trade Command Center</h1>
          <p className="brand-copy">
            One best setup first, every other ticker ranked around it.
          </p>
        </div>

        <div className="header-actions">
          <form className="search-shell" onSubmit={handleSearch}>
            <Search size={18} className="search-icon" />
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Jump to ticker (AAPL, NVDA...)"
              maxLength={5}
            />
          </form>

          <div className="refresh-shell">
            {lastUpdated && <span>Data refreshed: {lastUpdated}</span>}
            {!analysisReady && stocks && (
              <span style={{ fontSize: 12, opacity: 0.5 }}>Analyzing...</span>
            )}
            <button type="button" onClick={refresh} disabled={loading}>
              {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
            </button>
          </div>
        </div>
      </header>

      {loading && !stocks ? (
        <DashboardSkeleton />
      ) : featured ? (
        <main className="strategy-layout">
          <section className="featured-pick" onClick={() => handleCardClick(featured.ticker)}>
            <div className="featured-topline">
              <span className="featured-badge"><Sparkles size={14} /> Recommended Pick</span>
              <span className="featured-score">Composite Score {featured.score.toFixed(1)}</span>
            </div>

            <div className="featured-headline">
              <div>
                <h2>{featured.ticker}</h2>
                <p className="featured-price mono">Underlying Price: ${Number(featured.price || 0).toFixed(2)}</p>
              </div>
              <div className="featured-headline-right">
                <OutlookBadge strategy={featured.strategy} large />
                <div className={`featured-change ${Number(featured.change_pct) >= 0 ? 'green' : 'red'}`}>
                  {Number(featured.change_pct) >= 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />}
                  {Number(featured.change_pct) >= 0 ? '+' : ''}{featured.change_pct}%
                </div>
              </div>
            </div>

            <div className="featured-metrics">
              <Metric label="Strategy" value={formatStrategy(featured.strategy)} />
              <Metric label="Confidence" value={toPercent(featured.confidence)} accent />
              <Metric
                label="Max Profit"
                value={formatCurrency(featured.executionPlan?.summary?.max_profit)}
              />
              <Metric
                label="Max Loss"
                value={formatCurrency(featured.executionPlan?.summary?.max_loss)}
              />
            </div>

            <div className="featured-charts">
              <div className="chart-shell">
                <h3>30-Day Price Action</h3>
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={(featured.history || []).map((h) => ({ d: h.date?.slice(5), c: h.close }))}>
                    <defs>
                      <linearGradient id="heroPrice" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#35c2ff" stopOpacity={0.4} />
                        <stop offset="100%" stopColor="#35c2ff" stopOpacity={0.03} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#2e2a44" strokeDasharray="4 4" />
                    <XAxis dataKey="d" tick={{ fill: '#b7b5c8', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#b7b5c8', fontSize: 11 }} width={55} />
                    <Tooltip
                      contentStyle={{ background: '#17142a', border: '1px solid #333050', borderRadius: 10 }}
                      formatter={(value) => [`$${Number(value).toFixed(2)}`, 'Close']}
                    />
                    <Area type="monotone" dataKey="c" stroke="#35c2ff" strokeWidth={2} fill="url(#heroPrice)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-shell">
                <h3>Payoff at Expiration</h3>
                <PayoffChart executionPlan={featured.executionPlan} />
              </div>
            </div>

            <div className="setup-shell">
              <h3>Options Trade Setup</h3>
              <p className="setup-subtitle">
                {featured.executionPlan?.expiry_meta?.date
                  ? `Expiration ${featured.executionPlan.expiry_meta.date} • ${featured.executionPlan.expiry_meta.signal || 'signal unavailable'}`
                  : 'Execution plan from cached options chain'}
              </p>

              {(featured.executionPlan?.legs || []).length > 0 ? (
                <div className="setup-table-wrap">
                  <table className="setup-table mono">
                    <thead>
                      <tr>
                        <th>Side</th>
                        <th>Type</th>
                        <th>Strike</th>
                        <th>Bid</th>
                        <th>Ask</th>
                        <th>Mid</th>
                      </tr>
                    </thead>
                    <tbody>
                      {featured.executionPlan.legs.map((leg, index) => (
                        <tr key={`${leg.side}-${leg.type}-${leg.strike}-${index}`}>
                          <td>{leg.side}</td>
                          <td>{leg.type}</td>
                          <td>{formatCurrency(leg.strike)}</td>
                          <td>{formatCurrency(leg.bid)}</td>
                          <td>{formatCurrency(leg.ask)}</td>
                          <td>{formatCurrency(leg.mid)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="setup-empty">Option legs are still warming up from cache for this ticker.</p>
              )}
            </div>
          </section>

          <aside className="surrounding-panel">
            <div className="panel-heading">
              <h3><TrendingUp size={16} /> Next Best Opportunities</h3>
            </div>
            <div className="opportunity-grid">
              {surrounding.map((stock) => (
                <button
                  type="button"
                  key={stock.ticker}
                  className="opportunity-card"
                  onClick={() => handleCardClick(stock.ticker)}
                >
                  <div className="opportunity-top">
                    <strong>{stock.ticker}</strong>
                    <span className={`opportunity-change ${Number(stock.change_pct) >= 0 ? 'green' : 'red'}`}>
                      {Number(stock.change_pct) >= 0 ? '+' : ''}{stock.change_pct}%
                    </span>
                  </div>

                  <p className="opportunity-strategy">{formatStrategy(stock.strategy)}</p>

                  <OutlookBadge strategy={stock.strategy} />

                  <div className="opportunity-metrics">
                    <span><Target size={13} /> Conf {toPercent(stock.confidence)}</span>
                    <span>Max P {formatCurrency(stock.executionPlan?.summary?.max_profit)}</span>
                    <span>Max L {formatCurrency(stock.executionPlan?.summary?.max_loss)}</span>
                  </div>

                  <p className="opportunity-price mono">Underlying Price: ${Number(stock.price || 0).toFixed(2)}</p>
                </button>
              ))}
            </div>
          </aside>
        </main>
      ) : (
        <DashboardSkeleton />
      )}

      {/* Detail modal */}
      {detailLoading && (
        <div className="detail-overlay">
          <div className="ring-spinner-wrap">
            <div className="ring-spinner" />
            <span className="ring-spinner-label">Analyzing options...</span>
          </div>
        </div>
      )}
      {detail && !detailLoading && (
        <StockDetail data={detail} onClose={clear} />
      )}
    </div>
  );
}

function Metric({ label, value, accent = false }) {
  return (
    <div className={`featured-metric ${accent ? 'accent' : ''}`}>
      <span>{label}</span>
      <strong className="mono">{value}</strong>
    </div>
  );
}

function PayoffChart({ executionPlan }) {
  const payoffData = (executionPlan?.payoff_curve || []).map((point) => ({
    ...point,
    profitZone: point.pnl > 0 ? point.pnl : null,
    lossZone: point.pnl < 0 ? point.pnl : null,
  }));

  if (payoffData.length === 0) {
    return (
      <div className="empty-payoff">
        <p>Execution plan unavailable for this ticker yet.</p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <ComposedChart data={payoffData}>
        <defs>
          <linearGradient id="heroProfit" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#24d798" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#24d798" stopOpacity={0.08} />
          </linearGradient>
          <linearGradient id="heroLoss" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ff5470" stopOpacity={0.12} />
            <stop offset="100%" stopColor="#ff5470" stopOpacity={0.55} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#2e2a44" strokeDasharray="4 4" />
        <XAxis dataKey="price" tick={{ fill: '#b7b5c8', fontSize: 11 }} />
        <YAxis tick={{ fill: '#b7b5c8', fontSize: 11 }} width={64} />
        <Tooltip
          contentStyle={{ background: '#17142a', border: '1px solid #333050', borderRadius: 10 }}
          formatter={(value) => [`$${Number(value).toFixed(2)}`, 'P/L']}
          labelFormatter={(label) => `Underlying: $${label}`}
        />
        <Area type="monotone" dataKey="profitZone" baseValue={0} fill="url(#heroProfit)" stroke="none" connectNulls={false} />
        <Area type="monotone" dataKey="lossZone" baseValue={0} fill="url(#heroLoss)" stroke="none" connectNulls={false} />
        <ReferenceLine y={0} stroke="#ffd56b" strokeDasharray="4 4" />
        <Line type="monotone" dataKey="pnl" stroke="#7ac9ff" strokeWidth={2} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function toPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatCurrency(value) {
  if (value == null) return '--';
  return `$${Number(value).toFixed(2)}`;
}

function formatStrategy(strategy) {
  if (strategy === null || strategy === undefined) return '—';
  if (strategy === 'NO_TRADE') return 'No Trade';
  return strategy.replaceAll('_', ' ');
}

function getOutlook(strategy) {
  if (strategy === null || strategy === undefined) return { label: '…', tone: 'neutral', Icon: Minus };
  const normalized = String(strategy || '').toUpperCase();
  if (normalized.includes('BULL')) {
    return { label: 'Bullish', tone: 'bullish', Icon: TrendingUp };
  }
  if (normalized.includes('BEAR')) {
    return { label: 'Bearish', tone: 'bearish', Icon: TrendingDown };
  }
  if (normalized === 'NO_TRADE') {
    return { label: 'Neutral', tone: 'neutral', Icon: Minus };
  }
  if (normalized.includes('IRON_CONDOR') || normalized.includes('STRADDLE') || normalized.includes('STRANGLE')) {
    return { label: 'Neutral', tone: 'neutral', Icon: Minus };
  }
  return { label: 'Neutral', tone: 'neutral', Icon: Minus };
}

function OutlookBadge({ strategy, large = false }) {
  const { label, tone, Icon } = getOutlook(strategy);
  return (
    <span className={`outlook-badge ${tone} ${large ? 'large' : ''}`}>
      <Icon size={large ? 15 : 13} />
      Outlook: {label}
    </span>
  );
}
