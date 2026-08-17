import { useEffect, useState } from "react";
import { getBriefs } from "../api.js";
import BriefText from "./BriefText.jsx";

export default function BriefHistory() {
  const [briefs, setBriefs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getBriefs()
      .then((data) => {
        if (!cancelled) setBriefs(data.briefs || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Failed to load briefs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <p className="muted">Loading brief history…</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (briefs.length === 0) {
    return <p className="muted">No briefs yet — check back after the next scheduled run.</p>;
  }

  return (
    <div className="brief-history">
      <h2>Brief History</h2>
      <ul className="brief-list">
        {briefs.map((brief) => {
          const changeClass =
            brief.dayChangePct > 0
              ? "positive"
              : brief.dayChangePct < 0
              ? "negative"
              : "";
          return (
            <li key={brief.sk || brief.date} className="brief-list-item">
              <div className="brief-list-header">
                <span className="brief-date">{brief.date}</span>
                <span className={`brief-change ${changeClass}`}>
                  {typeof brief.dayChangePct === "number"
                    ? `${brief.dayChangePct > 0 ? "+" : ""}${brief.dayChangePct.toFixed(2)}%`
                    : "—"}
                </span>
              </div>
              <BriefText
                text={brief.text}
                paragraphClassName="brief-list-text"
                listClassName="brief-bullets"
                itemClassName="brief-list-text"
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
