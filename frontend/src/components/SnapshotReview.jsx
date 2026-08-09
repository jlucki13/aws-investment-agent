import { useEffect, useState } from "react";
import { getSnapshot, confirmSnapshot, rejectSnapshot } from "../api.js";

function toEditableRows(extractedPositions) {
  return (extractedPositions || []).map((p, i) => ({
    key: `${p.ticker}-${i}`,
    ticker: p.ticker || "",
    shares: p.shares ?? "",
    costBasis: p.costBasis ?? "",
    confidence: p.confidence || "medium",
  }));
}

export default function SnapshotReview({ snapshotId, onDone }) {
  const [snapshot, setSnapshot] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSnapshot(snapshotId)
      .then((data) => {
        if (cancelled) return;
        setSnapshot(data);
        setRows(toEditableRows(data.extractedPositions));
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Failed to load snapshot.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshotId]);

  function updateRow(key, field, value) {
    setRows((prev) =>
      prev.map((row) => (row.key === key ? { ...row, [field]: value } : row))
    );
  }

  function removeRow(key) {
    setRows((prev) => prev.filter((row) => row.key !== key));
  }

  async function handleConfirm() {
    setError(null);

    const cleaned = [];
    for (const row of rows) {
      const ticker = row.ticker.trim().toUpperCase();
      const shares = parseFloat(row.shares);
      const costBasis = parseFloat(row.costBasis);
      if (!ticker) {
        setError("Every row needs a ticker.");
        return;
      }
      if (Number.isNaN(shares) || shares <= 0) {
        setError(`Shares for ${ticker || "a row"} must be a positive number.`);
        return;
      }
      if (Number.isNaN(costBasis) || costBasis < 0) {
        setError(`Cost basis for ${ticker || "a row"} must be a non-negative number.`);
        return;
      }
      cleaned.push({ ticker, shares, costBasis });
    }

    if (cleaned.length === 0) {
      setError("Add at least one position, or use Reject instead.");
      return;
    }

    setSubmitting(true);
    try {
      await confirmSnapshot(snapshotId, cleaned);
      onDone();
    } catch (err) {
      setError(err.message || "Failed to confirm snapshot.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReject() {
    setSubmitting(true);
    setError(null);
    try {
      await rejectSnapshot(snapshotId);
      onDone();
    } catch (err) {
      setError(err.message || "Failed to reject snapshot.");
      setSubmitting(false);
    }
  }

  if (loading) return <p className="muted">Loading snapshot…</p>;
  if (error && !snapshot) return <p className="error">Error: {error}</p>;

  return (
    <div className="snapshot-review">
      <h2>Review Extracted Positions</h2>
      <p className="muted">
        Compare each row against the screenshot before confirming. Nothing
        is saved to your portfolio until you press Confirm.
      </p>

      <div className="review-layout">
        <div className="review-image-pane">
          {snapshot?.imageUrl ? (
            <img
              className="review-image"
              src={snapshot.imageUrl}
              alt="Uploaded brokerage screenshot"
            />
          ) : (
            <p className="muted">No image available.</p>
          )}
        </div>

        <div className="review-table-pane">
          <table className="table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Shares</th>
                <th>Cost basis</th>
                <th>Confidence</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.key}
                  className={row.confidence === "low" ? "row-low-confidence" : ""}
                >
                  <td>
                    <input
                      type="text"
                      value={row.ticker}
                      onChange={(e) => updateRow(row.key, "ticker", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      value={row.shares}
                      onChange={(e) => updateRow(row.key, "shares", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      value={row.costBasis}
                      onChange={(e) => updateRow(row.key, "costBasis", e.target.value)}
                    />
                  </td>
                  <td>
                    <span className={`badge badge-confidence-${row.confidence}`}>
                      {row.confidence}
                    </span>
                  </td>
                  <td>
                    <button className="danger-link" onClick={() => removeRow(row.key)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No rows left. Reject this snapshot or add a row manually
                    via the Positions tab instead.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="review-actions">
        <button onClick={handleConfirm} disabled={submitting}>
          {submitting ? "Confirming…" : "Confirm"}
        </button>
        <button className="secondary" onClick={handleReject} disabled={submitting}>
          Reject
        </button>
      </div>
    </div>
  );
}
