import { useEffect, useRef, useState } from "react";
import {
  createUploadUrl,
  uploadSnapshotFile,
  getSnapshot,
} from "../api.js";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 60000;

const ACCEPTED_TYPES = ["image/png", "image/jpeg"];

export default function ScreenshotUpload({ onReadyForReview }) {
  const [file, setFile] = useState(null);
  const [stage, setStage] = useState("idle"); // idle | uploading | polling | timeout | failed
  const [error, setError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const pollTimerRef = useRef(null);
  const pollDeadlineRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  function handleFileChange(e) {
    const selected = e.target.files?.[0] || null;
    setError(null);
    setSnapshot(null);
    setStage("idle");
    if (selected && !ACCEPTED_TYPES.includes(selected.type)) {
      setError("Please choose a PNG or JPEG image.");
      setFile(null);
      return;
    }
    setFile(selected);
  }

  async function handleUpload() {
    if (!file) return;
    setError(null);
    setStage("uploading");
    try {
      const { snapshotId, uploadUrl } = await createUploadUrl(
        file.name,
        file.type
      );
      await uploadSnapshotFile(uploadUrl, file);
      setStage("polling");
      pollDeadlineRef.current = Date.now() + POLL_TIMEOUT_MS;
      pollStatus(snapshotId);
    } catch (err) {
      setError(err.message || "Upload failed.");
      setStage("failed");
    }
  }

  function pollStatus(snapshotId) {
    getSnapshot(snapshotId)
      .then((data) => {
        setSnapshot(data);
        if (data.status === "PENDING_REVIEW") {
          onReadyForReview(snapshotId);
          return;
        }
        if (data.status === "EXTRACTION_FAILED") {
          setStage("failed");
          return;
        }
        if (Date.now() >= pollDeadlineRef.current) {
          setStage("timeout");
          return;
        }
        pollTimerRef.current = setTimeout(() => pollStatus(snapshotId), POLL_INTERVAL_MS);
      })
      .catch((err) => {
        setError(err.message || "Failed to check snapshot status.");
        setStage("failed");
      });
  }

  return (
    <div className="screenshot-upload">
      <h2>Add Positions from a Screenshot</h2>
      <p className="muted">
        Upload a screenshot of your brokerage holdings. It will be read
        automatically, but you always get to review and correct the numbers
        before anything is saved.
      </p>

      <div className="upload-controls">
        <input
          type="file"
          accept="image/png,image/jpeg"
          onChange={handleFileChange}
          disabled={stage === "uploading" || stage === "polling"}
        />
        <button
          onClick={handleUpload}
          disabled={!file || stage === "uploading" || stage === "polling"}
        >
          {stage === "uploading" ? "Uploading…" : "Upload"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {stage === "polling" && (
        <p className="muted">
          Processing screenshot… this usually takes a few seconds.
        </p>
      )}

      {stage === "timeout" && (
        <div className="warning-box">
          <p>
            Still processing after a minute — check back shortly. This tab
            will keep showing the upload form; you can come back and
            re-check by visiting this tab again, or wait a bit and reload.
          </p>
        </div>
      )}

      {stage === "failed" && (
        <div className="warning-box">
          <p>
            {snapshot?.error
              ? `Extraction failed: ${snapshot.error}`
              : error || "Something went wrong processing this screenshot."}
          </p>
          <p>
            You can add the position manually instead using the Positions
            tab.
          </p>
        </div>
      )}
    </div>
  );
}
