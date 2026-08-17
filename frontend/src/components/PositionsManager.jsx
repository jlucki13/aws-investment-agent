import { useEffect, useState } from "react";
import { getPositions, getPrices, upsertPosition, deletePosition } from "../api.js";
import { formatUsd } from "../format.js";

const emptyForm = { ticker: "", shares: "", costBasis: "" };

export default function PositionsManager() {
  const [positions, setPositions] = useState([]);
  const [prices, setPrices] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [deletingTicker, setDeletingTicker] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    return Promise.all([
      getPositions(),
      // Prices are a nice-to-have column -- don't let a failure here block
      // the positions table itself from loading.
      getPrices().catch(() => ({ prices: {} })),
    ])
      .then(([positionsRes, pricesRes]) => {
        setPositions(positionsRes.positions || []);
        setPrices(pricesRes.prices || {});
      })
      .catch((err) => setError(err.message || "Failed to load positions."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError(null);

    const ticker = form.ticker.trim().toUpperCase();
    const shares = parseFloat(form.shares);
    const costBasis = parseFloat(form.costBasis);

    if (!ticker) {
      setFormError("Ticker is required.");
      return;
    }
    if (Number.isNaN(shares) || shares <= 0) {
      setFormError("Shares must be a positive number.");
      return;
    }
    if (Number.isNaN(costBasis) || costBasis < 0) {
      setFormError("Cost basis must be a non-negative number.");
      return;
    }

    setSubmitting(true);
    try {
      await upsertPosition(ticker, { shares, costBasis });
      setForm(emptyForm);
      await load();
    } catch (err) {
      setFormError(err.message || "Failed to save position.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(ticker) {
    setDeletingTicker(ticker);
    setError(null);
    try {
      await deletePosition(ticker);
      await load();
    } catch (err) {
      setError(err.message || "Failed to delete position.");
    } finally {
      setDeletingTicker(null);
    }
  }

  return (
    <div className="positions-manager">
      <div className="section-heading">
        <h2>Positions</h2>
        {positions.length > 0 && (
          <span className="muted small">
            {positions.length} holding{positions.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      <form className="add-position-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Ticker (e.g. AAPL)"
          value={form.ticker}
          onChange={(e) => setForm({ ...form, ticker: e.target.value })}
        />
        <input
          type="number"
          step="any"
          placeholder="Shares"
          value={form.shares}
          onChange={(e) => setForm({ ...form, shares: e.target.value })}
        />
        <input
          type="number"
          step="any"
          placeholder="Cost basis"
          value={form.costBasis}
          onChange={(e) => setForm({ ...form, costBasis: e.target.value })}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Saving…" : "Add / Update"}
        </button>
      </form>
      {formError && <p className="error">{formError}</p>}

      {loading ? (
        <p className="muted">Loading positions…</p>
      ) : error ? (
        <p className="error">Error: {error}</p>
      ) : positions.length === 0 ? (
        <p className="muted">No positions yet — add one above.</p>
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
                <th>Status</th>
                <th>Updated</th>
                <th></th>
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
                      : <span className="muted">not set</span>}
                  </td>
                  <td className="num">
                    {price?.close != null ? formatUsd(Number(price.close)) : "—"}
                  </td>
                  <td className="num">
                    {marketValue != null ? formatUsd(marketValue) : "—"}
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
                  <td className="muted small">
                    {pos.updatedAt ? new Date(pos.updatedAt).toLocaleString() : "—"}
                  </td>
                  <td>
                    <button
                      className="danger-link"
                      onClick={() => handleDelete(pos.ticker)}
                      disabled={deletingTicker === pos.ticker}
                    >
                      {deletingTicker === pos.ticker ? "Deleting…" : "Delete"}
                    </button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
