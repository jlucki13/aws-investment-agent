// Shared helpers for rendering signed monetary/percentage figures the way a
// finance quote page does: consistent sign, fixed decimal formatting, and an
// up/down glyph that always agrees with the text color next to it.

export function changeClass(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "";
}

export function changeArrow(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  if (value > 0) return "▲";
  if (value < 0) return "▼";
  return "";
}

export function formatSignedPct(value, digits = 2) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatSignedUsd(value, digits = 2) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const sign = value >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(value).toFixed(digits)}`;
}

export function formatUsd(value, digits = 2) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}
