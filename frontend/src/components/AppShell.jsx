import { Suspense } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useFlow } from "../context/FlowContext";

const steps = [
  { number: "01", label: "EV", path: "/", ready: () => true },
  {
    number: "02",
    label: "Intelligence",
    path: "/intelligence",
    ready: (flow) => Boolean(flow.ev && flow.priority),
  },
  {
    number: "03",
    label: "Route",
    path: "/route",
    ready: (flow) => Boolean(flow.recommendation && flow.selectedCharger),
  },
  {
    number: "04",
    label: "Reservation",
    path: "/reservation",
    ready: (flow) => Boolean(flow.recommendation),
  },
  {
    number: "05",
    label: "Simulation",
    path: "/simulation",
    ready: (flow) => Boolean(flow.ev),
  },
];

export default function AppShell() {
  const { flow, resetFlow } = useFlow();
  const location = useLocation();
  const activeStep = steps.findIndex((step) => step.path === location.pathname);

  function startOver() {
    resetFlow();
  }

  return (
    <div className="min-h-screen bg-[#f3f6f3] text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <Link
            to="/"
            onClick={startOver}
            className="flex min-w-0 items-center gap-3"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-emerald-800 text-sm font-black text-white">
              GF
            </span>
            <span className="min-w-0">
              <span className="block text-lg font-semibold leading-tight tracking-normal">
                GridFlow
              </span>
              <span className="hidden text-xs text-slate-500 sm:block">
                Intelligent EV Charging Orchestrator
              </span>
            </span>
          </Link>
          <div className="hidden text-right sm:block">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
              Active vehicle
            </p>
            <p className="mt-1 max-w-48 truncate text-sm font-medium text-slate-700">
              {flow.evId || "No EV selected"}
            </p>
          </div>
        </div>
        <nav
          aria-label="EV charging journey"
          className="overflow-x-auto border-t border-slate-100"
        >
          <ol className="mx-auto flex min-w-max max-w-7xl items-center gap-1 px-4 py-2 sm:px-6 lg:px-8">
            {steps.map((step, index) => {
              const isReady = step.ready(flow);
              const isCurrent = index === activeStep;
              const content = (
                <>
                  <span
                    className={`grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold ${
                      isCurrent
                        ? "bg-emerald-800 text-white"
                        : index < activeStep
                          ? "bg-emerald-100 text-emerald-900"
                          : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {step.number.slice(1)}
                  </span>
                  <span>{step.label}</span>
                </>
              );
              const className = `flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                isCurrent
                  ? "text-emerald-900"
                  : isReady
                    ? "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
                    : "cursor-not-allowed text-slate-400"
              }`;

              return (
                <li key={step.path} className="flex items-center">
                  {isReady ? (
                    <NavLink
                      to={step.path}
                      aria-current={isCurrent ? "step" : undefined}
                      className={className}
                    >
                      {content}
                    </NavLink>
                  ) : (
                    <span aria-disabled="true" className={className}>
                      {content}
                    </span>
                  )}
                  {index < steps.length - 1 ? (
                    <span aria-hidden="true" className="mx-1 text-slate-300">
                      /
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-7 sm:px-6 sm:py-9 lg:px-8">
        <Suspense
          fallback={
            <p
              role="status"
              className="py-12 text-center text-sm text-slate-600"
            >
              Loading journey step…
            </p>
          }
        >
          <Outlet />
        </Suspense>
      </main>

      <footer className="mx-auto flex max-w-7xl items-center justify-between px-4 pb-8 text-xs text-slate-500 sm:px-6 lg:px-8">
        <span>GridFlow · Chennai charging network</span>
        <Link
          to="/"
          onClick={startOver}
          className="font-semibold text-emerald-800 hover:text-emerald-950"
        >
          Start over
        </Link>
      </footer>
    </div>
  );
}
