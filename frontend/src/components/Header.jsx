import { Search, RefreshCw, Loader2 } from 'lucide-react';
import { useState } from 'react';
import './Header.css';

export default function Header({ onSearch, lastUpdated, onRefresh, loading }) {
  const [input, setInput] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (ticker) onSearch(ticker);
  };

  return (
    <header className="header">
      <div className="header-left">
        <h1 className="logo">
          <span className="logo-icon">◆</span> Dashy
        </h1>
        <span className="logo-sub">Covered Call Intelligence</span>
      </div>

      <form className="search-bar" onSubmit={handleSubmit}>
        <Search size={18} className="search-icon" />
        <input
          type="text"
          placeholder="Search ticker (e.g. AAPL)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={5}
          className="search-input"
        />
      </form>

      <div className="header-right">
        {lastUpdated && (
          <span className="last-updated">Last updated: {lastUpdated}</span>
        )}
        <button
          className="refresh-btn"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh data"
        >
          {loading ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <RefreshCw size={16} />
          )}
        </button>
      </div>
    </header>
  );
}
