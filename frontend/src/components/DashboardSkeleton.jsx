import './DashboardSkeleton.css';

function Bone({ w = '100%', h = '16px', r = '8px', style = {} }) {
  return <div className="shimmer-bone" style={{ width: w, height: h, borderRadius: r, ...style }} />;
}

export default function DashboardSkeleton() {
  return (
    <div className="skeleton-layout">
      <div className="skeleton-featured">
        <div className="skeleton-topline">
          <Bone w="140px" h="26px" r="999px" />
          <Bone w="80px" h="13px" />
        </div>
        <div className="skeleton-headline">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Bone w="110px" h="58px" r="12px" />
            <Bone w="210px" h="20px" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
            <Bone w="110px" h="26px" r="999px" />
            <Bone w="64px" h="20px" r="8px" />
          </div>
        </div>
        <div className="skeleton-metrics">
          {[0, 1, 2, 3].map((i) => <Bone key={i} h="64px" r="14px" />)}
        </div>
        <Bone h="196px" r="14px" />
        <Bone h="196px" r="14px" />
        <Bone h="120px" r="14px" />
      </div>

      <div className="skeleton-panel">
        <Bone w="180px" h="20px" />
        <div className="skeleton-grid">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="skeleton-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <Bone w="56px" h="24px" r="6px" />
                <Bone w="42px" h="16px" r="6px" />
              </div>
              <Bone w="90px" h="13px" r="6px" />
              <Bone w="76px" h="22px" r="999px" style={{ marginTop: 8 }} />
              <Bone h="14px" r="6px" style={{ marginTop: 12 }} />
              <Bone w="110px" h="14px" r="6px" style={{ marginTop: 6 }} />
              <Bone w="130px" h="16px" r="6px" style={{ marginTop: 10 }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
