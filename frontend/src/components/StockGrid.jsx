import StockCard from './StockCard';
import './StockGrid.css';

export default function StockGrid({ stocks, onStockClick }) {
  if (!stocks || stocks.length === 0) return null;

  return (
    <section className="stock-grid-section">
      <h2 className="section-heading">Market Overview</h2>
      <div className="stock-grid">
        {stocks.map((s) => (
          <StockCard key={s.ticker} stock={s} onClick={onStockClick} />
        ))}
      </div>
    </section>
  );
}
