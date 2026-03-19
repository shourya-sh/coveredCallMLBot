import { AreaChart, Area, ResponsiveContainer, YAxis } from 'recharts';
import { TrendingUp, TrendingDown } from 'lucide-react';
import './StockCard.css';

export default function StockCard({ stock, onClick }) {
  const positive = stock.change_pct >= 0;
  const chartColor = positive ? '#00d68f' : '#ff4d4f';
  const chartData = (stock.history || []).map((h) => ({ close: h.close }));

  return (
    <div className="stock-card" onClick={() => onClick?.(stock.ticker)}>
      <div className="stock-card-top">
        <span className="stock-ticker">{stock.ticker}</span>
        <span className={`stock-change ${positive ? 'green' : 'red'}`}>
          {positive ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
          {positive ? '+' : ''}{stock.change_pct}%
        </span>
      </div>

      <div className="stock-price mono">${stock.price.toFixed(2)}</div>

      <div className="stock-spark">
        <ResponsiveContainer width="100%" height={48}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id={`grad-${stock.ticker}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={chartColor} stopOpacity={0.3} />
                <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <YAxis domain={['dataMin', 'dataMax']} hide />
            <Area
              type="monotone"
              dataKey="close"
              stroke={chartColor}
              strokeWidth={1.5}
              fill={`url(#grad-${stock.ticker})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
