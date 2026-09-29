import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useFlow } from "../context/FlowContext";
import { fetchEvSlotRecommendation } from "../services/evService";
import { createReservation } from "../services/reservationService";

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function ChargingReservation() {
  const { flow, updateFlow } = useFlow();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchEvSlotRecommendation(flow.evId)
      .then((slot) => {
        if (active) updateFlow({ slot });
      })
      .catch((requestError) => {
        if (active)
          setError(requestError.message || "A charging slot is unavailable.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [flow.evId]);

  async function reserveSlot() {
    if (!flow.slot) return;
    setSubmitting(true);
    setError("");
    try {
      const reservation = await createReservation({
        ev_id: flow.evId,
        charger_id: flow.slot.charger_id,
        slot_start: flow.slot.slot.start,
        slot_end: flow.slot.slot.end,
      });
      updateFlow({ reservation });
    } catch (requestError) {
      setError(requestError.message || "Unable to reserve this charging slot.");
    } finally {
      setSubmitting(false);
    }
  }

  const slot = flow.slot;
  const chargerMatches =
    slot?.charger_id === flow.recommendation?.recommendation?.charger_id;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Step 04 · Charging slot
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">
            A practical time to charge.
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Slot and capacity checks are calculated by the backend for{" "}
            {flow.evId}.
          </p>
        </div>
        <Link
          to="/route"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:border-slate-400"
        >
          Back to route
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
      {loading ? (
        <p
          role="status"
          className="rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600"
        >
          Finding a conflict-free charging slot…
        </p>
      ) : null}

      {slot ? (
        <section className="grid gap-5 lg:grid-cols-[1fr_0.8fr]">
          <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Recommended charger
            </p>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-2xl font-semibold text-slate-950">
                {slot.station_name}
              </h2>
              <span className="rounded-md bg-slate-100 px-3 py-1.5 text-xs font-bold uppercase text-slate-700">
                {chargerMatches ? "Recommended station" : "Available station"}
              </span>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              {slot.explanation}
            </p>
            <dl className="mt-6 grid gap-x-6 gap-y-5 border-t border-slate-100 pt-5 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Slot start
                </dt>
                <dd className="mt-1 text-sm font-semibold">
                  {formatDate(slot.slot.start)}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Slot end
                </dt>
                <dd className="mt-1 text-sm font-semibold">
                  {formatDate(slot.slot.end)}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Predicted waiting
                </dt>
                <dd className="mt-1 text-lg font-semibold">
                  {slot.slot.waiting_minutes} min
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Charging duration
                </dt>
                <dd className="mt-1 text-lg font-semibold">
                  {slot.slot.charging_duration_minutes} min
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Energy required
                </dt>
                <dd className="mt-1 text-lg font-semibold">
                  {slot.charging.energy_required_kwh} kWh
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Charging power
                </dt>
                <dd className="mt-1 text-lg font-semibold">
                  {slot.charging.charging_power_kw} kW
                </dd>
              </div>
            </dl>
          </article>

          <aside className="flex flex-col rounded-xl bg-slate-950 p-6 text-white sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-300">
              Grid and capacity
            </p>
            <p className="mt-2 text-2xl font-semibold">{slot.grid_status}</p>
            <p className="mt-1 text-sm text-slate-300">
              Grid risk {slot.grid_risk_score}/100 ·{" "}
              {slot.slot.serviceable_connector_capacity} serviceable connectors
            </p>
            <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-white/15 pt-5">
              <div>
                <dt className="text-xs text-slate-400">Priority level</dt>
                <dd className="mt-1 font-semibold">{slot.priority.level}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Slot score</dt>
                <dd className="mt-1 font-semibold">{slot.slot.score}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Occupied connectors</dt>
                <dd className="mt-1 font-semibold">
                  {slot.slot.occupied_connectors}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Grid suitability</dt>
                <dd className="mt-1 font-semibold">
                  {slot.slot.grid_suitability_score}/100
                </dd>
              </div>
            </dl>
            <button
              type="button"
              onClick={reserveSlot}
              disabled={submitting || Boolean(flow.reservation)}
              className="mt-auto rounded-lg bg-emerald-500 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting
                ? "Reserving slot…"
                : flow.reservation
                  ? "Slot reserved"
                  : "Reserve Charging Slot"}
            </button>
          </aside>
        </section>
      ) : null}

      {flow.reservation ? (
        <section
          aria-live="polite"
          className="rounded-xl border border-emerald-300 bg-emerald-50 p-5 sm:p-6"
        >
          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-800">
            Reservation confirmed
          </p>
          <h2 className="mt-2 text-xl font-semibold text-emerald-950">
            {flow.reservation.id}
          </h2>
          <p className="mt-2 text-sm text-emerald-900">
            {flow.reservation.charger_id} ·{" "}
            {formatDate(flow.reservation.slot_start)} to{" "}
            {formatDate(flow.reservation.slot_end)} · {flow.reservation.status}
          </p>
        </section>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <Link
          to="/route"
          className="px-2 py-2 text-sm font-semibold text-slate-600 hover:text-slate-950"
        >
          Back
        </Link>
        <Link
          to="/simulation"
          className="rounded-lg bg-emerald-800 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-900"
        >
          View Grid Impact
        </Link>
      </div>
    </div>
  );
}
