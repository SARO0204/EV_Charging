import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useFlow } from "../context/FlowContext";
import {
  fetchCharger,
  fetchChargerGrid,
  fetchQueuePrediction,
} from "../services/chargerService";
import { fetchEvRecommendation } from "../services/evService";

function Metric({ label, value, detail }) {
  return (
    <div className="border-l-2 border-emerald-700 pl-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold text-slate-950">{value}</p>
      {detail ? <p className="mt-1 text-xs text-slate-500">{detail}</p> : null}
    </div>
  );
}

export default function ChargingIntelligence() {
  const { flow, updateFlow } = useFlow();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [supportErrors, setSupportErrors] = useState([]);

  useEffect(() => {
    let active = true;
    async function loadIntelligence() {
      setLoading(true);
      setError("");
      try {
        const recommendation = await fetchEvRecommendation(flow.evId);
        const chargerId = recommendation.recommendation.charger_id;
        const results = await Promise.allSettled([
          fetchCharger(chargerId),
          fetchQueuePrediction(chargerId),
          fetchChargerGrid(chargerId),
        ]);
        if (!active) return;

        const [chargerResult, queueResult, gridResult] = results;
        const failures = results.flatMap((result, index) =>
          result.status === "rejected"
            ? [
                `${["Charger location", "Queue prediction", "Grid intelligence"][index]}: ${result.reason.message}`,
              ]
            : [],
        );
        updateFlow({
          recommendation,
          selectedCharger:
            chargerResult.status === "fulfilled" ? chargerResult.value : null,
          queue: queueResult.status === "fulfilled" ? queueResult.value : null,
          grid: gridResult.status === "fulfilled" ? gridResult.value : null,
          slot: null,
          reservation: null,
        });
        setSupportErrors(failures);
      } catch (requestError) {
        if (active)
          setError(
            requestError.message || "Charging intelligence is unavailable.",
          );
      } finally {
        if (active) setLoading(false);
      }
    }

    loadIntelligence();
    return () => {
      active = false;
    };
  }, [flow.evId]);

  const priority = flow.priority;
  const recommendation = flow.recommendation?.recommendation;
  const alternatives = flow.recommendation?.alternatives || [];
  const factors = Object.entries(priority?.factors || {});

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Step 02 · Charging intelligence
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">
            A recommendation with its reasoning.
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Backend analysis for {flow.evId} · priority{" "}
            {priority?.priority_level || "pending"}
          </p>
        </div>
        <Link
          to="/"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:border-slate-400"
        >
          Back to EV
        </Link>
      </header>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
        >
          {error}
        </p>
      ) : null}
      {supportErrors.map((message) => (
        <p
          key={message}
          role="status"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
        >
          {message}
        </p>
      ))}

      <section className="grid gap-5 lg:grid-cols-[0.85fr_1.15fr]">
        <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            EV priority
          </p>
          {priority ? (
            <>
              <div className="mt-4 flex items-end gap-3">
                <span className="text-5xl font-semibold tabular-nums text-slate-950">
                  {priority.priority_score}
                </span>
                <span className="mb-1 rounded-md bg-emerald-100 px-2.5 py-1 text-xs font-bold uppercase text-emerald-900">
                  {priority.priority_level}
                </span>
              </div>
              <p className="mt-4 text-sm leading-6 text-slate-600">
                {priority.explanation}
              </p>
              <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4">
                {factors.map(([name, factor]) => (
                  <div key={name}>
                    <dt className="text-xs text-slate-500">
                      {name.replaceAll("_", " ")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-800">
                      {factor.score}/100 · {factor.contribution} contribution
                    </dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <p className="mt-4 text-sm text-slate-500">Priority is loading…</p>
          )}
        </article>

        <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Recommended charger
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">
                {recommendation?.station_name ||
                  (loading ? "Evaluating stations…" : "No recommendation")}
              </h2>
            </div>
            {recommendation ? (
              <span className="rounded-md bg-emerald-800 px-3 py-1.5 text-sm font-semibold text-white">
                {recommendation.score} score
              </span>
            ) : null}
          </div>
          {recommendation ? (
            <>
              <p className="mt-4 text-sm leading-6 text-slate-600">
                {recommendation.explanation}
              </p>
              <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-5 border-t border-slate-100 pt-5 sm:grid-cols-4">
                <Metric
                  label="Predicted wait"
                  value={`${flow.queue?.predicted_wait_minutes ?? recommendation.predicted_wait_minutes} min`}
                  detail={
                    flow.queue
                      ? `${flow.queue.predicted_queue_count} EVs forecast`
                      : "From recommendation"
                  }
                />
                <Metric
                  label="Grid status"
                  value={flow.grid?.grid_status || recommendation.grid_status}
                  detail={
                    flow.grid
                      ? `${flow.grid.projected_peak_utilization_percent}% projected`
                      : "Current assessment"
                  }
                />
                <Metric
                  label="Grid risk"
                  value={`${flow.grid?.grid_risk_score ?? recommendation.grid_risk_score}/100`}
                  detail="Backend grid intelligence"
                />
                <Metric
                  label="Suitable power"
                  value={`${recommendation.suitable_charging_power_kw} kW`}
                  detail={`${recommendation.available_charging_power_kw} kW available`}
                />
              </div>
            </>
          ) : null}
        </article>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Other evaluated options
            </p>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">
              Alternatives
            </h2>
          </div>
          <p className="text-xs text-slate-500">
            Sorted by backend recommendation score
          </p>
        </div>
        {alternatives.length ? (
          <div className="mt-4 divide-y divide-slate-100">
            {alternatives.map((alternative) => (
              <div
                key={alternative.charger_id}
                className="grid gap-2 py-3 sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-6"
              >
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    {alternative.station_name}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {alternative.reason}
                  </p>
                </div>
                <span className="text-sm tabular-nums text-slate-600">
                  {alternative.predicted_wait_minutes} min wait
                </span>
                <span className="text-sm font-semibold tabular-nums text-slate-800">
                  {alternative.score}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-500">
            {loading
              ? "Evaluating alternatives…"
              : "No additional candidates were returned."}
          </p>
        )}
      </section>

      <div className="flex items-center justify-between gap-3">
        <Link
          to="/"
          className="px-2 py-2 text-sm font-semibold text-slate-600 hover:text-slate-950"
        >
          Back
        </Link>
        {flow.selectedCharger ? (
          <Link
            to="/route"
            className="rounded-lg bg-emerald-800 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-900"
          >
            View Route
          </Link>
        ) : (
          <span className="text-sm text-slate-500">
            {loading
              ? "Loading charger location…"
              : "Charger location unavailable"}
          </span>
        )}
      </div>
    </div>
  );
}
