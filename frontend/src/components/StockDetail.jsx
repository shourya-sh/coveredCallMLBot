import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import {
  ArrowUpRight, ArrowDownRight, Shield, Target, Clock, AlertTriangle, X,
} from 'lucide-react';
import './StockDetail.css';

export default function StockDetail({ data, onClose }) {
  if (!data) return null;

  const positive = data.change_pct >= 0;
  const rec = data.recommendation;
  const analysis = data.analysis;
  const actionLabel = analysis?.top_strategy || rec?.action;
  const explanation = rec?.explanation || buildAnalysisExplanation(analysis);
  const confidence = analysis?.confidence != null
    ? `${Math.round(analysis.confidence * 100)}%`
    : rec?.confidence;
  const chartData = (data.history || []).map((h) => ({
    date: h.date?.slice(5), // MM-DD
    close: h.close,
  }));

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
        <button className="detail-close" onClick={onClose}><X size={20} /></button>

        {/* ── Header ── */}
        <div className="detail-header">
          <div>
            <h2 className="detail-ticker">{data.ticker}</h2>
            <p className="detail-price mono">
              ${Number(data.price ?? 0).toFixed(2)}
              <span className={`detail-chg ${positive ? 'green' : 'red'}`}>
                {positive ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                {positive ? '+' : ''}{data.change_pct}%
              </span>
            </p>
          </div>
          {actionLabel && (
            <span className={`action-badge ${actionLabel === 'NO_TRADE' ? 'hold' : 'sell'}`}>
              {actionLabel}
            </span>
          )}
        </div>

        {/* ── Chart ── */}
        <div className="detail-chart">
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="detailGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#58a6ff" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#58a6ff" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#2a3040" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fill: '#8b949e', fontSize: 11 }} />
              <YAxis domain={['auto', 'auto']} tick={{ fill: '#8b949e', fontSize: 11 }} width={60} />
              <Tooltip
                contentStyle={{ background: '#1a1f2e', border: '1px solid #2a3040', borderRadius: 8 }}
                labelStyle={{ color: '#8b949e' }}
                itemStyle={{ color: '#e6edf3' }}
              />
              <Area type="monotone" dataKey="close" stroke="#58a6ff" strokeWidth={2} fill="url(#detailGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* ── Recommendation ── */}
        {(rec || analysis) && (
          <div className="detail-rec">
            <h3 className="section-title">Strategy Recommendation</h3>
            <p className="rec-explanation">{explanation}</p>

            {confidence && (
              <span className="confidence-badge medium">
                Confidence: {confidence}
              </span>
            )}

            {analysis?.probabilities && (
              <div className="metrics-grid">
                {Object.entries(analysis.probabilities).map(([name, value]) => (
                  <MetricBox key={name} label={name} value={`${(value * 100).toFixed(1)}%`} />
                ))}
              </div>
            )}

            {rec?.contract && (
              <div className="metrics-grid">
                <MetricBox icon={<Target size={16} />} label="Strike" value={`$${rec.contract.strike}`} />
                <MetricBox icon={<Clock size={16} />} label="Expiration" value={rec.contract.expiration} />
                <MetricBox icon={<ArrowUpRight size={16} />} label="Premium" value={`$${rec.contract.premium}`} />
                {rec.contract.delta != null && (
                  <MetricBox icon={<Shield size={16} />} label="Delta" value={rec.contract.delta.toFixed(2)} />
                )}
              </div>
            )}

            {rec?.metrics && (
              <div className="metrics-grid">
                <MetricBox label="Premium Yield" value={`${rec.metrics.premium_yield}%`} />
                <MetricBox label="Annualized Return" value={`${rec.metrics.annualized_return}%`} />
                <MetricBox label="Max Profit" value={`$${rec.metrics.max_profit}`} />
                <MetricBox label="Downside Protection" value={`${rec.metrics.downside_protection}%`} />
                <MetricBox label="Break-Even" value={`$${rec.metrics.break_even_price}`} />
                {rec.metrics.assignment_probability != null && (
                  <MetricBox label="Assignment Prob." value={`${rec.metrics.assignment_probability}%`} />
                )}
              </div>
            )}

            {analysis?.execution_plan?.legs && (
              <div className="alternatives">
                <h4>Execution Plan</h4>
                {analysis?.options_chain_source && (
                  <p className="rec-explanation">
                    Options data source: {analysis.options_chain_source}
                    {analysis.options_chain_updated_at ? ` (updated ${analysis.options_chain_updated_at})` : ''}
                  </p>
                )}
                {analysis?.execution_plan?.summary && (
                  <div className="metrics-grid">
                    <MetricBox label="Upfront Credit" value={`$${analysis.execution_plan.summary.upfront_credit ?? 0}`} />
                    <MetricBox label="Max Profit" value={analysis.execution_plan.summary.max_profit == null ? 'Unlimited' : `$${analysis.execution_plan.summary.max_profit}`} />
                    <MetricBox label="Max Loss" value={`$${analysis.execution_plan.summary.max_loss ?? 0}`} />
                  </div>
                )}
                <table className="alt-table">
                  <thead>
                    <tr><th>Side</th><th>Type</th><th>Strike</th><th>Mid</th></tr>
                  </thead>
                  <tbody>
                    {analysis.execution_plan.legs.map((leg, i) => (
                      <tr key={i}>
                        <td>{leg.side}</td>
                        <td>{leg.type}</td>
                        <td>${leg.strike}</td>
                        <td>${leg.mid}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {rec?.warnings && rec.warnings.length > 0 && (
              <div className="warnings">
                {rec.warnings.map((w, i) => (
                  <div key={i} className="warning-item">
                    <AlertTriangle size={14} /> {w}
                  </div>
                ))}
              </div>
            )}

            {rec?.alternatives && rec.alternatives.length > 0 && (
              <div className="alternatives">
                <h4>Alternative Contracts</h4>
                <table className="alt-table">
                  <thead>
                    <tr><th>Strike</th><th>Expiration</th><th>Premium</th><th>Score</th></tr>
                  </thead>
                  <tbody>
                    {rec.alternatives.map((a, i) => (
                      <tr key={i}>
                        <td>${a.strike}</td>
                        <td>{a.expiration}</td>
                        <td>${a.premium}</td>
                        <td>{a.score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function buildAnalysisExplanation(analysis) {
  if (!analysis) return 'No analysis available.';
  if (analysis.top_strategy === 'NO_TRADE') {
    return 'No-trade conditions detected based on recent market features, confidence, and risk filters.';
  }
  return `Model suggests ${analysis.top_strategy} from recent trend, momentum, and volatility features.`;
}

function MetricBox({ icon, label, value }) {
  return (
    <div className="metric-box">
      {icon && <span className="metric-icon">{icon}</span>}
      <span className="metric-label">{label}</span>
      <span className="metric-value mono">{value}</span>
    </div>
  );
}
