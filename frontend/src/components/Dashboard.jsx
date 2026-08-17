import { useEffect, useState } from "react";
import { getLatestBrief, getPositions, getPrices, ApiError } from "../api.js";
import BriefText from "./BriefText.jsx";
import {
  changeArrow,
  changeClass,
  formatSignedPct,
  formatSignedUsd,
  formatUsd,
} from "../format.js";

export default function Dashboard() {
  const [brief, setBrief] = useState(null);
  const [noBrief, setNoBrief] = useState(false);
  const [positions, setPositions] = useState([]);
  const [prices, setPrices] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setNoBrief(false);
      try {
        const [briefResult, positionsResult, pricesResult] =
          await Promise.allSettled([
            getLatestBrief(),
            getPositions(),
            getPrices(),
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

        // Prices are a nice-to-have column, not core dashboard data -- a
        // failure here shouldn't block the rest of the page from rendering.
        if (pricesResult.status === "fulfilled") {
          setPrices(pricesResult.value.prices || {});
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

  const dayChangeCls = changeClass(brief?.dayChangePct);

  return (
    <div className="dashboard">
      <section className="quote-panel">
        <div className="quote-header">
          <div className="quote-price-block">
            <span className="quote-label">Total Portfolio Value</span>
            <div className="quote-price-row">
              <span className="quote-price">{formatUsd(brief.totalValue)}</span>
              <span className={`quote-change ${dayChangeCls}`}>
                <span className={`arrow ${dayChangeCls}`}>
                  {changeArrow(brief.dayChangePct)}
                </span>
                {formatSignedUsd(brief.dayChangeValue)} (
                {formatSignedPct(brief.dayChangePct)})
              </span>
            </div>
            <span className="quote-timestamp">As of {brief.date}</span>
          </div>

          <div className="quote-stats-strip">
            <div className="quote-stat">
              <span className="quote-stat-label">Unrealized</span>
              <span className={`quote-stat-value ${changeClass(brief.unrealizedPct)}`}>
                {formatSignedPct(brief.unrealizedPct)}
              </span>
            </div>
            <div className="quote-stat">
              <span className="quote-stat-label">Effective Holdings</span>
              <span className="quote-stat-value">
                {brief.effectiveHoldings?.toFixed(2)}
              </span>
            </div>
            <div className="quote-stat">
              <span className="quote-stat-label">Positions</span>
              <span className="quote-stat-value">{brief.positionCount}</span>
            </div>
          </div>
        </div>

        {brief.missingQuotes && brief.missingQuotes.length > 0 && (
          <p className="warning">
            Missing quotes for: {brief.missingQuotes.join(", ")}
          </p>
        )}

        <div className="brief-narrative">
          <h3>Daily Brief</h3>
          <BriefText
            text={brief.text}
            paragraphClassName="brief-text"
            listClassName="brief-bullets"
            itemClassName="brief-text"
          />
        </div>

        <p className="diversification-note">
          <strong>Effective holdings</strong> — {brief.positionCount} position
          {brief.positionCount === 1 ? "" : "s"}, but concentration means it
          behaves like ~{brief.effectiveHoldings?.toFixed(1)} equally-weighted
          positions. Lower means more concentrated risk.
        </p>
      </section>

      <section className="positions-section">
        <div className="section-heading">
          <h2>Positions</h2>
          {positions.length > 0 && (
            <span className="muted small">
              {positions.length} holding{positions.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
        {positions.length === 0 ? (
          <p className="muted">No positions yet.</p>
        ) : (
          <div className="positions-table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="num">Shares</th>
                  <th className="num">Cost Basis</th>
                  <th className="num">Price</th>
                  <th className="num">Mkt Value</th>
                  <th className="num">Weight</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const price = prices[pos.ticker];
                  const marketValue =
                    price?.close != null ? pos.shares * price.close : null;
                  return (
                    <tr key={pos.ticker}>
                      <td className="ticker-cell">{pos.ticker}</td>
                      <td className="num">{pos.shares}</td>
                      <td className="num">
                        {pos.costBasis != null
                          ? formatUsd(Number(pos.costBasis))
                          : "—"}
                      </td>
                      <td className="num">
                        {price?.close != null ? (
                          <span className="price-cell">
                            <span>{formatUsd(Number(price.close))}</span>
                            {typeof price.changePct === "number" && (
                              <span
                                className={`change-inline ${changeClass(
                                  price.changePct
                                )}`}
                              >
                                <span
                                  className={`arrow ${changeClass(
                                    price.changePct
                                  )}`}
                                >
                                  {changeArrow(price.changePct)}
                                </span>
                                {formatSignedPct(price.changePct)}
                              </span>
                            )}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="num">
                        {marketValue != null ? formatUsd(marketValue) : "—"}
                      </td>
                      <td className="num">
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
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
