import { lazy } from "react";
import {
  createBrowserRouter,
  Link,
  Navigate,
  RouterProvider,
} from "react-router-dom";

import AppShell from "./components/AppShell";
import { FlowProvider, useFlow } from "./context/FlowContext";
const ChargingIntelligence = lazy(() => import("./pages/ChargingIntelligence"));
const ChargingReservation = lazy(() => import("./pages/ChargingReservation"));
const EVConsole = lazy(() => import("./pages/EVConsole"));
const GridImpact = lazy(() => import("./pages/GridImpact"));
const RecommendedRoute = lazy(() => import("./pages/RecommendedRoute"));

function RequireFlow({ field, fields, children }) {
  const { flow } = useFlow();
  const requiredFields = fields || [field];
  if (requiredFields.every((requiredField) => Boolean(flow[requiredField]))) {
    return children;
  }

  return (
    <section className="mx-auto max-w-3xl rounded-xl border border-amber-200 bg-amber-50 p-8 text-center">
      <p className="text-xs font-semibold uppercase tracking-widest text-amber-700">
        EV journey not ready
      </p>
      <h1 className="mt-3 text-2xl font-semibold text-slate-950">
        Analyze an EV first.
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        This step needs intelligence from an EV analysis.
      </p>
      <Link
        to="/"
        className="mt-6 inline-flex rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800"
      >
        Go to EV Console
      </Link>
    </section>
  );
}

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <EVConsole /> },
      {
        path: "/intelligence",
        element: (
          <RequireFlow field="ev">
            <ChargingIntelligence />
          </RequireFlow>
        ),
      },
      {
        path: "/route",
        element: (
          <RequireFlow fields={["ev", "recommendation", "selectedCharger"]}>
            <RecommendedRoute />
          </RequireFlow>
        ),
      },
      {
        path: "/reservation",
        element: (
          <RequireFlow field="recommendation">
            <ChargingReservation />
          </RequireFlow>
        ),
      },
      {
        path: "/simulation",
        element: (
          <RequireFlow field="ev">
            <GridImpact />
          </RequireFlow>
        ),
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

function App() {
  return (
    <FlowProvider>
      <RouterProvider router={router} />
    </FlowProvider>
  );
}

export default App;
