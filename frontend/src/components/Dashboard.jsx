import { useEffect, useState } from "react";
import { getLatestBrief, getPositions, ApiError } from "../api.js";

export default function Dashboard() {
  const [brief, setBrief] = useState(null);
  const [noBrief, setNoBrief] = useState(false);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setNoBrief(false);
      try {
        const [briefResult, positionsResult] = await Promise.allSettled([
          getLatestBrief(),
          getPositions(),
        ]);

        if (cancelled) return;

        if (briefResult.status === "fulfilled") {
          setBrief(briefResult.value);
        } else if (
          briefResult.reason instanceof ApiError &&
          briefResult.reason.status === 404
        ) {
          setNoBrief(true);
        } else {
          throw briefResult.reason;
        }

        if (positionsResult.status === "fulfilled") {
          setPositions(positionsResult.value.positions || []);
        } else {
          throw positionsResult.reason;
        }
      } catch (err) {
        if (!cancelled) setError(err.message || "Failed to load dashboard.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p className="muted">Loading dashboard…</p>;
  if (error) return <p className="error">Error: {error}</p>;

  if (noBrief) {
    return (
      <div className="empty-state">
        <h2>No brief yet</h2>
        <p>
          The daily brief hasn't run for this account yet. It runs on
          weekday afternoons after market close, once you have at least one
          confirmed position. Check back after the next scheduled run, or
          add a position now under the Positions tab.
        </p>
      </div>
    );
  }

  const weightByTicker = new Map(
    (brief?.weights || []).map((w) => [w.ticker, w.weight_pct])
  );

  const dayChangeClass =
    brief?.dayChangePct > 0 ? "positive" : brief?.dayChangePct < 0 ? "negative" : "";

  return (
    <div className="dashboard">
      <section className="brief-card">
        <p className="brief-text">{brief.text}</p>
        <div className="brief-stats">
          <div className="stat">
            <span className="stat-label">Total value</span>
            <span className="stat-value">
              ${brief.totalValue?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Day change</span>
            <span className={`stat-value ${dayChangeClass}`}>
              {brief.dayChangePct > 0 ? "+" : ""}
              {brief.dayChangePct?.toFixed(2)}%
              {typeof brief.dayChangeValue === "number" && (
                <span className="stat-subvalue">
                  {" "}
                  ({brief.dayChangeValue >= 0 ? "+" : ""}$
                  {brief.dayChangeValue.toFixed(2)})
                </span>
              )}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Unrealized</span>
            <span className={`stat-value ${brief.unrealizedPct >= 0 ? "positive" : "negative"}`}>
              {brief.unrealizedPct > 0 ? "+" : ""}
              {brief.unrealizedPct?.toFixed(2)}%
            </span>
          </div>
        </div>
        <div className="diversification-callout">
          <div className="diversification-number">
            {brief.effectiveHoldings?.toFixed(2)}
          </div>
          <div className="diversification-copy">
            <strong>Effective holdings</strong> — {brief.positionCount} position
            {brief.positionCount === 1 ? "" : "s"}, but concentration means it
            behaves like ~{brief.effectiveHoldings?.toFixed(1)} equally-weighted
            positions. Lower means more concentrated risk.
          </div>
        </div>
        {brief.missingQuotes && brief.missingQuotes.length > 0 && (
          <p className="warning">
            Missing quotes for: {brief.missingQuotes.join(", ")}
          </p>
        )}
        <p className="muted small">As of {brief.date}</p>
      </section>

      <section>
        <h2>Positions</h2>
        {positions.length === 0 ? (
          <p className="muted">No positions yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Shares</th>
                <th>Cost basis</th>
                <th>Weight</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.ticker}>
                  <td>{pos.ticker}</td>
                  <td>{pos.shares}</td>
                  <td>${Number(pos.costBasis).toFixed(2)}</td>
                  <td>
                    {weightByTicker.has(pos.ticker)
                      ? `${weightByTicker.get(pos.ticker).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td>
                    <span
                      className={
                        pos.status === "CONFIRMED"
                          ? "badge badge-confirmed"
                          : "badge badge-pending"
                      }
                    >
                      {pos.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
