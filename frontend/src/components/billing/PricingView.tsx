"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { RequireAuth } from "@/components/auth/AuthProvider";
import {
  changePlan,
  getAccount,
  getPlans,
  startCheckout,
  syncCheckout,
  type Account,
  type Plan,
  type PlanId,
  type PlansResponse,
} from "@/lib/api";
import { openCheckout } from "@/lib/paddle";

export function PricingView() {
  return (
    <RequireAuth>
      <div className="flex min-h-screen flex-col">
        <AppHeader />
        <Pricing />
      </div>
    </RequireAuth>
  );
}

function Pricing() {
  const router = useRouter();
  const [plans, setPlans] = useState<PlansResponse | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [busy, setBusy] = useState<PlanId | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getPlans(), getAccount()])
      .then(([p, a]) => {
        setPlans(p);
        setAccount(a);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const hasPaidPlan = account ? account.plan !== "free" : false;

  const choose = async (plan: Plan) => {
    if (!plans || !account) return;
    setError(null);
    setBusy(plan.id);
    try {
      if (hasPaidPlan) {
        const verb = plan.price_usd_month > (planById(plans, account.plan)?.price_usd_month ?? 0)
          ? "Upgrade"
          : "Switch";
        if (!window.confirm(`${verb} to ${plan.name} ($${plan.price_usd_month}/month)? The difference is charged or credited straight away.`)) {
          return;
        }
        setAccount(await changePlan(plan.id));
        router.push("/dashboard?plan=changed");
        return;
      }
      const res = await startCheckout(plan.id);
      if (res.done) {
        router.push("/dashboard?checkout=done");
        return;
      }
      const txn = await openCheckout({
        environment: plans.paddle?.environment ?? "sandbox",
        priceId: res.price_id,
        email: res.email,
        customData: res.custom_data,
      });
      if (txn) {
        await syncCheckout(txn);
        router.push("/dashboard?checkout=done");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <div>
        <h1 className="text-2xl font-semibold">Plans</h1>
        <p className="text-muted">
          Minutes are live interview time (while the copilot is listening). Pausing doesn&apos;t count. Usage resets on
          the 1st of each month.
        </p>
      </div>
      {plans?.provider === "fake" && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-700 dark:text-amber-300">
          Test mode: no payment provider is connected, so plans switch instantly and nothing is charged.
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        {(plans?.plans ?? []).map((plan) => {
          const current = account?.plan === plan.id;
          const featured = plan.id === "pro";
          let label = hasPaidPlan ? `Switch to ${plan.name}` : `Get ${plan.name}`;
          if (current) label = "Your plan";
          else if (plan.id === "free") label = hasPaidPlan ? "Cancel from your dashboard" : "Included";
          const disabled = current || plan.id === "free" || !plan.available || busy !== null;
          return (
            <section
              key={plan.id}
              className={`flex flex-col gap-4 rounded-xl border bg-surface p-5 ${
                featured ? "border-primary" : "border-black/10 dark:border-white/10"
              }`}
            >
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold">
                  {plan.name}
                  {current && (
                    <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">Current</span>
                  )}
                </h2>
                <p className="text-sm text-muted">{plan.blurb}</p>
              </div>
              <p>
                <span className="text-3xl font-semibold">${plan.price_usd_month}</span>
                <span className="text-muted"> / month</span>
              </p>
              <ul className="flex flex-col gap-1 text-sm">
                <li>✓ {plan.minutes} live interview minutes a month</li>
                <li>✓ Answers grounded in your CV and the job</li>
                <li>✓ Interview history with transcripts</li>
              </ul>
              <button
                onClick={() => choose(plan)}
                disabled={disabled}
                className={`mt-auto rounded-lg px-4 py-2 font-medium disabled:cursor-default disabled:opacity-60 ${
                  featured && !current ? "bg-primary text-primary-foreground hover:opacity-90" : "border border-black/15 hover:bg-black/5 dark:border-white/15 dark:hover:bg-white/5"
                }`}
              >
                {busy === plan.id ? "Opening…" : plan.available || plan.id === "free" ? label : "Not available yet"}
              </button>
            </section>
          );
        })}
      </div>
    </main>
  );
}

function planById(plans: PlansResponse, id: PlanId): Plan | undefined {
  return plans.plans.find((p) => p.id === id);
}
