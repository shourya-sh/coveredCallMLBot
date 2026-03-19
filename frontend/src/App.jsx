import { useDashboardStocks, useStockLookup } from './hooks';
import Header from './components/Header';
import TickerStrip from './components/TickerStrip';
import StockGrid from './components/StockGrid';
import StockDetail from './components/StockDetail';
import LoadingSpinner from './components/LoadingSpinner';
import './App.css';

export default function App() {
  const { data: stocks, loading, lastUpdated, refresh } = useDashboardStocks();
  const { result: detail, loading: detailLoading, lookup, clear } = useStockLookup();

  const handleSearch = (ticker) => lookup(ticker);
  const handleCardClick = (ticker) => lookup(ticker);

  return (
    <div className="app">
      <Header
        onSearch={handleSearch}
        lastUpdated={lastUpdated}
        onRefresh={refresh}
        loading={loading}
      />

      {/* Rotating ticker strip */}
      <TickerStrip stocks={stocks} onStockClick={handleCardClick} />

      {/* Main grid */}
      {loading && !stocks ? (
        <LoadingSpinner message="Fetching market data..." />
      ) : (
        <StockGrid stocks={stocks} onStockClick={handleCardClick} />
      )}

      {/* Detail modal */}
      {detailLoading && (
        <div className="detail-overlay">
          <LoadingSpinner message="Analyzing options..." />
        </div>
      )}
      {detail && !detailLoading && (
        <StockDetail data={detail} onClose={clear} />
      )}
    </div>
  );
}
