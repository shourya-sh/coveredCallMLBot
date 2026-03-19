import { useState, useEffect, useRef } from 'react';
import StockCard from './StockCard';
import './Ticker.css';

const ROTATE_INTERVAL = 4000; // ms per visible set

export default function TickerStrip({ stocks, onStockClick }) {
  const [offset, setOffset] = useState(0);
  const ref = useRef(null);

  useEffect(() => {
    if (!stocks || stocks.length === 0) return;
    const id = setInterval(() => {
      setOffset((prev) => (prev + 1) % stocks.length);
    }, ROTATE_INTERVAL);
    return () => clearInterval(id);
  }, [stocks]);

  if (!stocks || stocks.length === 0) return null;

  // Double the list for seamless scroll appearance
  const doubled = [...stocks, ...stocks];

  return (
    <div className="ticker-strip-wrapper">
      <div
        className="ticker-strip"
        ref={ref}
        style={{
          transform: `translateX(-${offset * 210}px)`,
          transition: 'transform .6s ease',
        }}
      >
        {doubled.map((s, i) => (
          <StockCard key={`${s.ticker}-${i}`} stock={s} onClick={onStockClick} />
        ))}
      </div>
    </div>
  );
}
