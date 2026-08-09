import { useState } from "react";
import Dashboard from "./components/Dashboard.jsx";
import BriefHistory from "./components/BriefHistory.jsx";
import PositionsManager from "./components/PositionsManager.jsx";
import ScreenshotUpload from "./components/ScreenshotUpload.jsx";
import SnapshotReview from "./components/SnapshotReview.jsx";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "history", label: "Brief History" },
  { id: "positions", label: "Positions" },
  { id: "upload", label: "Add from Screenshot" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  // Snapshot id that has reached PENDING_REVIEW and is awaiting human
  // confirmation. Lives at this level so the "Add from Screenshot" tab
  // can hand off from upload -> review without a router.
  const [reviewSnapshotId, setReviewSnapshotId] = useState(null);

  function handleReadyForReview(snapshotId) {
    setReviewSnapshotId(snapshotId);
  }

  function handleReviewDone() {
    setReviewSnapshotId(null);
    setActiveTab("positions");
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Portfolio Monitor</h1>
        <nav className="tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={tab.id === activeTab ? "tab active" : "tab"}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main">
        {activeTab === "dashboard" && <Dashboard />}
        {activeTab === "history" && <BriefHistory />}
        {activeTab === "positions" && <PositionsManager />}
        {activeTab === "upload" &&
          (reviewSnapshotId ? (
            <SnapshotReview
              snapshotId={reviewSnapshotId}
              onDone={handleReviewDone}
            />
          ) : (
            <ScreenshotUpload onReadyForReview={handleReadyForReview} />
          ))}
      </main>
    </div>
  );
}
