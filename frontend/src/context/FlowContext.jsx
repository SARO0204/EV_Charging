import { createContext, useContext, useEffect, useState } from "react";

const STORAGE_KEY = "gridflow-ev-journey";
const FlowContext = createContext(null);

function emptyFlow() {
  return {
    evId: "",
    ev: null,
    priority: null,
    recommendation: null,
    selectedCharger: null,
    queue: null,
    grid: null,
    slot: null,
    reservation: null,
  };
}

function readStoredFlow() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    return stored ? { ...emptyFlow(), ...stored } : emptyFlow();
  } catch {
    return emptyFlow();
  }
}

export function FlowProvider({ children }) {
  const [flow, setFlow] = useState(readStoredFlow);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(flow));
    } catch {
      // The current journey remains usable if browser storage is unavailable.
    }
  }, [flow]);

  function updateFlow(patch) {
    setFlow((current) => ({ ...current, ...patch }));
  }

  function resetFlow() {
    setFlow(emptyFlow());
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // The in-memory journey is still cleared.
    }
  }

  return (
    <FlowContext.Provider value={{ flow, updateFlow, resetFlow }}>
      {children}
    </FlowContext.Provider>
  );
}

export function useFlow() {
  const context = useContext(FlowContext);
  if (!context) {
    throw new Error("useFlow must be used inside FlowProvider.");
  }
  return context;
}
