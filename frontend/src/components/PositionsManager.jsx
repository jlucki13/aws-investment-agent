import { useEffect, useState } from "react";
import { getPositions, upsertPosition, deletePosition } from "../api.js";

const emptyForm = { ticker: "", shares: "", costBasis: "" };

export default function PositionsManager() {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [deletingTicker, setDeletingTicker] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    return getPositions()
      .then((data) => setPositions(data.positions || []))
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
      <h2>Positions</h2>

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
        <table className="table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Shares</th>
              <th>Cost basis</th>
              <th>Status</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => (
              <tr key={pos.ticker}>
                <td>{pos.ticker}</td>
                <td>{pos.shares}</td>
                <td>${Number(pos.costBasis).toFixed(2)}</td>
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
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
