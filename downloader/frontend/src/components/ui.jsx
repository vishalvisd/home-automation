import { LoaderCircle } from "lucide-react";

export function Card({ title, subtitle, right, children, className = "" }) {
  return (
    <section className={`rounded-3xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}>
      {(title || right) && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-lg font-semibold text-slate-950">{title}</h2>}
            {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Button({ children, icon: Icon, variant = "primary", busy = false, className = "", ...props }) {
  const styles = {
    primary: "bg-slate-900 text-white",
    danger: "bg-red-600 text-white",
    secondary: "border border-slate-300 bg-white text-slate-800",
    subtle: "bg-slate-100 text-slate-700",
  }[variant];

  return (
    <button
      type="button"
      className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold disabled:opacity-50 ${styles} ${className}`}
      disabled={busy || props.disabled}
      {...props}
    >
      {busy ? <LoaderCircle size={16} className="animate-spin" /> : Icon && <Icon size={16} />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm";

export function Badge({ tone = "slate", children }) {
  const tones = {
    slate: "bg-slate-100 text-slate-600",
    green: "bg-emerald-100 text-emerald-700",
    red: "bg-red-100 text-red-700",
    amber: "bg-amber-100 text-amber-700",
    blue: "bg-blue-100 text-blue-700",
  };
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Message({ error, message }) {
  if (error) return <p className="mt-4 text-sm text-red-700">{error}</p>;
  if (message) return <p className="mt-4 text-sm text-emerald-700">{message}</p>;
  return null;
}

export function Progress({ value }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
      <div
        className="h-full rounded-full bg-blue-600 transition-all"
        style={{ width: `${Math.round((value || 0) * 100)}%` }}
      />
    </div>
  );
}
