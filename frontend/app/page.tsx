"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ─── Helpers ────────────────────────────────────────────────────────────────
const fmt = (n: any) => (n != null && n !== "" ? Number(n).toLocaleString("fa-IR") : "—");
const fmtNum = (n: any) => (n != null && n !== "" ? Number(n).toLocaleString() : "—");
const fmtPct = (n: number, d: number) =>
  d > 0 ? Math.round((n / d) * 100) + "%" : "0%";

// ─── Types ───────────────────────────────────────────────────────────────────
interface Product {
  variant_id: number;
  title: string;
  is_buy_box_winner: boolean;
  current_price: number;
  reference_price: number;
  buy_box_price?: number;
  stock: number;
  seller_stock?: number;
  min_price: string | number;
  max_price: string | number;
  has_config: boolean;
  is_active?: boolean; // ← برای روشن/خاموش تنوع
}

interface BotState {
  is_running?: boolean;
  workspace_id?: number;
  step_price?: number;
  started_at?: string;
  cycle_count?: number;
  total_updates?: number;
  buybox_wins?: number;
  rate_limit_hits?: number;
}

interface Settings {
  lead_time: number;
  shipping_type: string;
  max_per_order: number;
  request_delay_min: number;
  request_delay_max: number;
  rate_limit_backoff_base: number;
  max_retries: number;
  buybox_formula: string;
  min_price_formula: string;
  auto_apply_min_price: boolean;
  strategy_mode: string;
  dry_run: boolean;
  variant_cooldown_seconds: number;
  max_price_change_percent: number;
  notify_webhook_url: string;
  rate_limit_pause_seconds: number;
  max_consecutive_failures: number;
}

const DEFAULT_SETTINGS: Settings = {
  lead_time: 2,
  shipping_type: "seller",
  max_per_order: 4,
  request_delay_min: 3.0,
  request_delay_max: 6.0,
  rate_limit_backoff_base: 15,
  max_retries: 3,
  buybox_formula: "competitor_price - step_price",
  min_price_formula: "",
  auto_apply_min_price: false,
  strategy_mode: "aggressive",
  dry_run: false,
  variant_cooldown_seconds: 300,
  max_price_change_percent: 8.0,
  notify_webhook_url: "",
  rate_limit_pause_seconds: 180,
  max_consecutive_failures: 10,
};

type ActiveTab = "dashboard" | "products" | "settings" | "logs";
type FilterMode = "all" | "winning" | "losing" | "configured" | "unconfigured";

// ─── Icons ───────────────────────────────────────────────────────────────────
const Icon = {
  Dashboard: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  Products: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
    </svg>
  ),
  Settings: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
    </svg>
  ),
  Logs: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14,2 14,8 20,8" />
      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><line x1="10" y1="9" x2="8" y2="9" />
    </svg>
  ),
  Play: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <polygon points="5,3 19,12 5,21" />
    </svg>
  ),
  Stop: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="3" y="3" width="18" height="18" rx="2" />
    </svg>
  ),
  Refresh: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="23,4 23,10 17,10" /><polyline points="1,20 1,14 7,14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  ),
  Save: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17,21 17,13 7,13" /><polyline points="7,3 7,8 15,8" />
    </svg>
  ),
  Search: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  ChevronDown: () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="6,9 12,15 18,9" />
    </svg>
  ),
  Trash: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="3,6 5,6 21,6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6M14 11v6" /><path d="M9 6V4h6v2" />
    </svg>
  ),
  Zap: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="13,2 3,14 12,14 11,22 21,10 12,10" />
    </svg>
  ),
  Trophy: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M6 9H4a2 2 0 0 1-2-2V5h4M18 9h2a2 2 0 0 0 2-2V5h-4" />
      <path d="M8 21h8M12 17v4" />
      <path d="M6 9a6 6 0 0 0 12 0V3H6v6z" />
    </svg>
  ),
  Toggle: ({ on }: { on: boolean }) => (
    <svg width="36" height="20" viewBox="0 0 36 20">
      <rect width="36" height="20" rx="10" fill={on ? "#22c55e" : "#374151"} />
      <circle cx={on ? "26" : "10"} cy="10" r="8" fill="white" style={{ transition: "cx 0.2s" }} />
    </svg>
  ),
  Warning: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  Copy: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  ),
};

// ─── Toast ────────────────────────────────────────────────────────────────────
interface Toast { id: number; msg: string; type: "success" | "error" | "info" }
let toastId = 0;

function ToastContainer({ toasts, remove }: { toasts: Toast[]; remove: (id: number) => void }) {
  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 pointer-events-none" style={{ minWidth: 320 }}>
      {toasts.map(t => (
        <div
          key={t.id}
          onClick={() => remove(t.id)}
          className="pointer-events-auto cursor-pointer px-5 py-3 rounded-xl text-sm font-medium shadow-2xl border backdrop-blur-sm"
          style={{
            background: t.type === "success" ? "rgba(20,83,45,0.97)" : t.type === "error" ? "rgba(127,29,29,0.97)" : "rgba(15,23,42,0.97)",
            borderColor: t.type === "success" ? "#16a34a55" : t.type === "error" ? "#dc262655" : "#1e40af55",
            color: t.type === "success" ? "#86efac" : t.type === "error" ? "#fca5a5" : "#93c5fd",
            animation: "toastIn 0.25s ease",
          }}
        >
          {t.type === "success" ? "✓ " : t.type === "error" ? "✗ " : "ℹ "}{t.msg}
        </div>
      ))}
    </div>
  );
}

// ─── Stat Card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, accent, pulse }: {
  label: string; value: any; sub?: string; accent: string; pulse?: boolean;
}) {
  return (
    <div className="relative rounded-2xl p-5 overflow-hidden border"
      style={{ background: "rgba(15,23,42,0.8)", borderColor: accent + "33" }}>
      <div className="absolute inset-0 opacity-10" style={{ background: `radial-gradient(circle at top right, ${accent}, transparent 70%)` }} />
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: accent }} />
          <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: accent }} />
        </span>
      )}
      <div className="relative">
        <div className="text-2xl font-bold font-mono tracking-tight" style={{ color: accent }}>{value}</div>
        <div className="text-xs mt-1.5" style={{ color: "#94a3b8" }}>{label}</div>
        {sub && <div className="text-[10px] mt-0.5" style={{ color: "#475569" }}>{sub}</div>}
      </div>
    </div>
  );
}

// ─── Badge ────────────────────────────────────────────────────────────────────
function Badge({ win }: { win: boolean }) {
  return win ? (
    <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full"
      style={{ background: "rgba(34,197,94,0.12)", color: "#4ade80", border: "1px solid #22c55e33" }}>
      <Icon.Trophy /> بای‌باکس
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full"
      style={{ background: "rgba(239,68,68,0.12)", color: "#f87171", border: "1px solid #ef444433" }}>
      <Icon.Warning /> رقابت
    </span>
  );
}

// ─── Formula Input ────────────────────────────────────────────────────────────
function FormulaInput({ label, hint, value, onChange, variables, onTest, testResult, presets }: {
  label: string; hint: string; value: string; onChange: (v: string) => void;
  variables: string[]; onTest: () => void;
  testResult: { success?: boolean; result?: number; error?: string } | null;
  presets: { label: string; formula: string }[];
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold" style={{ color: "#94a3b8" }}>{label}</label>
      <p className="text-[10px]" style={{ color: "#475569" }}>{hint}</p>
      <div className="flex flex-wrap gap-1.5">
        {presets.map(p => (
          <button key={p.formula} onClick={() => onChange(p.formula)}
            className="text-[10px] px-2 py-1 rounded-lg border transition-all"
            style={{
              background: value === p.formula ? "rgba(99,102,241,0.2)" : "rgba(15,23,42,0.8)",
              borderColor: value === p.formula ? "#6366f1" : "#1e293b",
              color: value === p.formula ? "#a5b4fc" : "#64748b",
            }}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <input type="text" value={value} onChange={e => onChange(e.target.value)}
          dir="ltr" className="flex-1 rounded-xl px-3 py-2 text-sm font-mono outline-none transition-all"
          style={{ background: "#0f172a", border: "1px solid #1e293b", color: "#e2e8f0" }} />
        <button onClick={onTest}
          className="px-3 py-2 rounded-xl text-xs font-semibold border transition-all hover:opacity-80"
          style={{ background: "rgba(99,102,241,0.15)", border: "1px solid #6366f133", color: "#a5b4fc" }}>
          تست
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        {variables.map(v => (
          <code key={v} onClick={() => onChange((value ? value + " " : "") + v)}
            className="text-[10px] px-2 py-0.5 rounded cursor-pointer transition-all hover:opacity-80"
            style={{ background: "#0f172a", border: "1px solid #1e293b", color: "#38bdf8" }}>
            {v}
          </code>
        ))}
      </div>
      {testResult && (
        <div className="text-xs px-3 py-2 rounded-xl border"
          style={{
            background: testResult.success ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            borderColor: testResult.success ? "#22c55e33" : "#ef444433",
            color: testResult.success ? "#4ade80" : "#f87171",
          }}>
          {testResult.success ? `✓ نتیجه: ${fmtNum(testResult.result)} تومان` : `✗ ${testResult.error}`}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ─── Main Component ───────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

export default function RepricerApp() {
  // ─── State ─────────────────────────────────────────────────────────────────
  const [tab, setTab] = useState<ActiveTab>("dashboard");
  const [products, setProducts] = useState<Product[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [botState, setBotState] = useState<BotState>({});
  const [isRunning, setIsRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [stepPrice, setStepPrice] = useState(1000);
  const [cycleDelay, setCycleDelay] = useState(120);
  const [workspaceId, setWorkspaceId] = useState(1);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [search, setSearch] = useState("");
  const [discoveringId, setDiscoveringId] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [applyingFormula, setApplyingFormula] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [buyboxTestResult, setBuyboxTestResult] = useState<any>(null);
  const [minPriceTestResult, setMinPriceTestResult] = useState<any>(null);
  const [bulkMin, setBulkMin] = useState("");
  const [bulkMax, setBulkMax] = useState("");
  const [sortBy, setSortBy] = useState<"price" | "title" | "stock" | "none">("none");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const logsRef = useRef<HTMLDivElement>(null);

  // ─── Toast ─────────────────────────────────────────────────────────────────
  const toast = useCallback((msg: string, type: Toast["type"] = "info") => {
    const id = ++toastId;
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
  }, []);
  const removeToast = useCallback((id: number) => setToasts(t => t.filter(x => x.id !== id)), []);

  // ─── Load Settings ─────────────────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/api/settings`).then(r => r.json()).then(d => {
      if (d.settings) setSettings(d.settings);
    }).catch(() => { });
  }, []);

  // ─── Polling ───────────────────────────────────────────────────────────────
  useEffect(() => {
    const poll = setInterval(() => {
      fetch(`${API}/api/logs?limit=200`).then(r => r.json()).then(d => {
        setLogs(d.logs || []);
        setIsRunning(!!d.is_running);
        setBotState(d.bot_state || {});
      }).catch(() => { });
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = 0;
  }, [logs]);

  // ─── Derived ───────────────────────────────────────────────────────────────
  const buyboxWinners = products.filter(p => p.is_buy_box_winner).length;
  const configured = products.filter(p => p.has_config || (p.min_price !== "" && p.max_price !== "")).length;
  const totalStock = products.reduce((a, p) => a + (p.seller_stock || p.stock || 0), 0);
  const uptime = botState.started_at
    ? Math.floor((Date.now() - new Date(botState.started_at).getTime()) / 60000) : 0;

  const filtered = products
    .filter(p => {
      if (filter === "winning") return p.is_buy_box_winner;
      if (filter === "losing") return !p.is_buy_box_winner;
      if (filter === "configured") return p.has_config || (p.min_price !== "" && p.max_price !== "");
      if (filter === "unconfigured") return !p.has_config && (p.min_price === "" || p.max_price === "");
      return true;
    })
    .filter(p => !search || p.title?.toLowerCase().includes(search.toLowerCase()) || String(p.variant_id).includes(search))
    .sort((a, b) => {
      if (sortBy === "none") return 0;
      const dir = sortDir === "asc" ? 1 : -1;
      if (sortBy === "price") return (a.current_price - b.current_price) * dir;
      if (sortBy === "stock") return ((a.seller_stock || a.stock) - (b.seller_stock || b.stock)) * dir;
      if (sortBy === "title") return a.title?.localeCompare(b.title || "") * dir;
      return 0;
    });

  // ─── Actions ───────────────────────────────────────────────────────────────
  const loadProducts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/products?workspace_id=${workspaceId}`);
      const data = await res.json();
      setProducts(data.variants || []);
      toast(`${data.total || 0} محصول دریافت شد`, "success");
    } catch {
      toast("خطا در ارتباط با سرور", "error");
    }
    setLoading(false);
  };

  const saveConfigs = async () => {
    setSaving(true);
    const configs: Record<string, any> = {};
    products.forEach(p => {
      if (p.min_price !== "" && p.max_price !== "") {
        configs[String(p.variant_id)] = {
          min_price: parseInt(String(p.min_price)),
          max_price: parseInt(String(p.max_price)),
        };
      }
    });
    try {
      const res = await fetch(`${API}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ configs }),
      });
      const d = await res.json();
      toast(`${d.saved_count} محصول ذخیره شد`, "success");
    } catch {
      toast("خطا در ذخیره‌سازی", "error");
    }
    setSaving(false);
  };

  const saveSettings = async () => {
    setSavingSettings(true);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      const data = await res.json();
      if (data.status === "success") toast("تنظیمات ذخیره شد", "success");
      else toast("خطا در ذخیره", "error");
    } catch {
      toast("خطا در ارتباط با سرور", "error");
    }
    setSavingSettings(false);
  };

  const toggleBot = async () => {
    if (isRunning) {
      await fetch(`${API}/api/bot/stop`, { method: "POST" });
      toast("ربات متوقف شد", "info");
    } else {
      await fetch(`${API}/api/bot/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId, step_price: stepPrice, cycle_delay: cycleDelay }),
      });
      toast("ربات شروع به کار کرد", "success");
    }
  };

  const autoDiscover = async (variant_id: number, reference_price: number, current_price: number) => {
    if (!confirm(`کشف خودکار بازه برای تنوع ${variant_id}؟ حدود ۶۰-۹۰ ثانیه طول می‌کشد.`)) return;
    setDiscoveringId(String(variant_id));
    try {
      const res = await fetch(`${API}/api/bot/discover_bounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          variant_id: String(variant_id),
          reference_price: parseInt(String(reference_price)) || parseInt(String(current_price)),
          current_price: parseInt(String(current_price)),
        }),
      });
      const data = await res.json();
      if (data.success) {
        setProducts(prev => prev.map(p =>
          String(p.variant_id) === String(variant_id)
            ? { ...p, min_price: data.min_price, max_price: data.max_price, has_config: true }
            : p
        ));
        toast(`کف: ${fmtNum(data.min_price)} | سقف: ${fmtNum(data.max_price)}`, "success");
      } else {
        toast("خطا: " + data.message, "error");
      }
    } catch {
      toast("خطای ارتباط با سرور", "error");
    }
    setDiscoveringId(null);
  };

  // ── Toggle variant active/inactive (API placeholder) ──────────────────────
  // NOTE: این تابع placeholder است. وقتی API آماده شد، این قسمت رو با endpoint واقعی جایگزین کن:
  // POST /api/variants/toggle  →  { variant_id, is_active }
  const toggleVariantActive = async (variant_id: number, current_active: boolean) => {
    setTogglingId(String(variant_id));
    try {
      // ─── PLACEHOLDER: اینجا باید API call واقعی باشه ───────────────────
      // const res = await fetch(`${API}/api/variants/toggle`, {
      //   method: "POST",
      //   headers: { "Content-Type": "application/json" },
      //   body: JSON.stringify({ variant_id, is_active: !current_active, workspace_id: workspaceId }),
      // });
      // const data = await res.json();
      // if (!data.success) throw new Error(data.message);
      // ─── PLACEHOLDER END ──────────────────────────────────────────────────

      // فعلا فقط state رو تغییر میدیم
      await new Promise(r => setTimeout(r, 400)); // شبیه‌سازی تاخیر شبکه
      setProducts(prev => prev.map(p =>
        p.variant_id === variant_id ? { ...p, is_active: !current_active } : p
      ));
      toast(`تنوع ${variant_id} ${!current_active ? "فعال" : "غیرفعال"} شد`, "success");
    } catch (e: any) {
      toast("خطا در تغییر وضعیت: " + e.message, "error");
    }
    setTogglingId(null);
  };

  // ── Bulk actions ──────────────────────────────────────────────────────────
  const applyBulkPrices = () => {
    if (!bulkMin && !bulkMax) { toast("حداقل یک مقدار وارد کن", "error"); return; }
    setProducts(prev => prev.map(p => {
      if (!selectedIds.has(p.variant_id)) return p;
      return {
        ...p,
        ...(bulkMin ? { min_price: parseInt(bulkMin) } : {}),
        ...(bulkMax ? { max_price: parseInt(bulkMax) } : {}),
      };
    }));
    toast(`${selectedIds.size} محصول آپدیت شد`, "success");
    setBulkMin(""); setBulkMax("");
  };

  const selectAll = () => {
    if (selectedIds.size === filtered.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filtered.map(p => p.variant_id)));
    }
  };

  const applyMinFormula = async () => {
    if (!settings.min_price_formula) { toast("فرمول کف قیمت وارد کن", "error"); return; }
    if (!confirm(`فرمول «${settings.min_price_formula}» به همه محصولات اعمال شود؟`)) return;
    setApplyingFormula(true);
    try {
      const res = await fetch(`${API}/api/bot/apply_min_formula`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId, formula: settings.min_price_formula, step_price: stepPrice }),
      });
      const data = await res.json();
      if (data.status === "success") {
        toast(`${data.updated_count} محصول آپدیت شد`, "success");
        await loadProducts();
      } else {
        toast("خطا: " + (data.message || JSON.stringify(data)), "error");
      }
    } catch {
      toast("خطای ارتباط با سرور", "error");
    }
    setApplyingFormula(false);
  };

  const testFormula = async (type: "buybox" | "min_price", formula: string) => {
    const sampleValues = type === "buybox"
      ? { competitor_price: 100000, reference_price: 150000, current_price: 98000, step_price: stepPrice, min_price: 70000, buy_box_price: 95000 }
      : { reference_price: 150000, current_price: 98000, step_price: stepPrice, cost: 60000 };
    try {
      const res = await fetch(`${API}/api/formula/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ formula, formula_type: type, sample_values: sampleValues }),
      });
      const data = await res.json();
      if (type === "buybox") setBuyboxTestResult(data);
      else setMinPriceTestResult(data);
    } catch {
      const err = { success: false, error: "خطا در ارتباط با سرور" };
      if (type === "buybox") setBuyboxTestResult(err);
      else setMinPriceTestResult(err);
    }
  };

  const handlePriceChange = (id: number, field: "min_price" | "max_price", value: string) => {
    setProducts(prev => prev.map(p => p.variant_id === id ? { ...p, [field]: value } : p));
  };

  const copyLog = () => {
    navigator.clipboard.writeText(logs.join("\n")).then(() => toast("لاگ‌ها کپی شد", "success"));
  };

  const clearLogs = () => {
    fetch(`${API}/api/logs`, { method: "DELETE" }).catch(() => { });
    toast("لاگ‌ها پاک شد", "info");
  };

  // ─── Styles ────────────────────────────────────────────────────────────────
  const styles = {
    sidebar: { width: 220, background: "#070d1a", borderRight: "1px solid #0f1f3d" } as const,
    main: { background: "#040b18" } as const,
    card: { background: "rgba(15,23,42,0.7)", border: "1px solid #0f1f3d", borderRadius: 16 } as const,
    input: { background: "#0a1628", border: "1px solid #162040", color: "#e2e8f0", borderRadius: 10, outline: "none" } as const,
    btn: (color: string) => ({
      background: color + "22", border: `1px solid ${color}44`, color: color,
      borderRadius: 10, cursor: "pointer", transition: "all 0.15s",
    }) as const,
    table: { width: "100%", borderCollapse: "collapse" as const },
  };

  const navItems: { id: ActiveTab; label: string; Icon: React.FC }[] = [
    { id: "dashboard", label: "داشبورد", Icon: Icon.Dashboard },
    { id: "products", label: "محصولات", Icon: Icon.Products },
    { id: "settings", label: "تنظیمات", Icon: Icon.Settings },
    { id: "logs", label: "لاگ‌ها", Icon: Icon.Logs },
  ];

  // ─── Render helpers ────────────────────────────────────────────────────────
  const renderDashboard = () => (
    <div className="space-y-6">
      {/* Bot control banner */}
      <div className="rounded-2xl p-6 flex items-center gap-6 border"
        style={{ background: isRunning ? "rgba(34,197,94,0.06)" : "rgba(15,23,42,0.8)", borderColor: isRunning ? "#22c55e33" : "#0f1f3d" }}>
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-1">
            <span className={`w-2.5 h-2.5 rounded-full ${isRunning ? "bg-green-400 animate-pulse" : "bg-slate-600"}`} />
            <h2 className="text-base font-bold" style={{ color: isRunning ? "#4ade80" : "#94a3b8" }}>
              {isRunning
                ? `در حال رقابت — چرخه #${botState.cycle_count || 0} | استراتژی: ${settings.strategy_mode}`
                : "ربات متوقف است"}
            </h2>
            {settings.dry_run && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                style={{ background: "rgba(251,191,36,0.15)", color: "#fbbf24", border: "1px solid #fbbf2433" }}>
                DRY RUN
              </span>
            )}
          </div>
          <p className="text-xs" style={{ color: "#475569" }}>
            {isRunning ? `آپ‌تایم: ${uptime} دقیقه | workspace: ${botState.workspace_id}` : "برای شروع روی دکمه کلیک کنید"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <label className="text-[10px]" style={{ color: "#475569" }}>گام قیمت</label>
              <input type="number" value={stepPrice} step={500}
                onChange={e => setStepPrice(Number(e.target.value))} disabled={isRunning}
                className="w-24 px-2 py-1 text-xs text-center"
                style={{ ...styles.input, opacity: isRunning ? 0.5 : 1 }} />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-[10px]" style={{ color: "#475569" }}>تاخیر (ثانیه)</label>
              <input type="number" value={cycleDelay} step={30}
                onChange={e => setCycleDelay(Number(e.target.value))} disabled={isRunning}
                className="w-24 px-2 py-1 text-xs text-center"
                style={{ ...styles.input, opacity: isRunning ? 0.5 : 1 }} />
            </div>
          </div>
          <button onClick={toggleBot}
            className="flex items-center gap-2 px-5 py-3 rounded-xl font-bold text-sm"
            style={{
              background: isRunning ? "rgba(239,68,68,0.15)" : "rgba(34,197,94,0.15)",
              border: `1px solid ${isRunning ? "#ef444444" : "#22c55e44"}`,
              color: isRunning ? "#f87171" : "#4ade80",
            }}>
            {isRunning ? <><Icon.Stop /> توقف</> : <><Icon.Play /> شروع</>}
          </button>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard label="کل محصولات" value={fmtNum(products.length)} sub={`${configured} تنظیم‌شده`} accent="#38bdf8" />
        <StatCard label="بای‌باکس" value={fmtNum(buyboxWinners)}
          sub={fmtPct(buyboxWinners, products.length) + " نرخ برد"} accent="#4ade80" pulse={isRunning && buyboxWinners > 0} />
        <StatCard label="در رقابت" value={fmtNum(products.length - buyboxWinners)} accent="#f87171" />
        <StatCard label="آپدیت قیمت" value={fmtNum(botState.total_updates || 0)} sub="جلسه جاری" accent="#c084fc" />
        <StatCard label="خطای 429" value={fmtNum(botState.rate_limit_hits || 0)} sub="محدودیت نرخ" accent="#fb923c" />
        <StatCard label="موجودی کل" value={fmtNum(totalStock)} sub="همه محصولات" accent="#22d3ee"
          pulse={isRunning} />
      </div>

      {/* Recent logs preview */}
      <div className="rounded-2xl overflow-hidden border" style={styles.card}>
        <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: "#0f1f3d" }}>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500/60" />
            <span className="w-2 h-2 rounded-full bg-yellow-500/60" />
            <span className="w-2 h-2 rounded-full bg-green-500/60" />
            <span className="text-xs font-mono ml-2" style={{ color: "#475569" }}>live log</span>
          </div>
          <div className="flex gap-2">
            <button onClick={copyLog} className="text-[10px] px-2 py-1 rounded-lg flex items-center gap-1" style={styles.btn("#64748b")}>
              <Icon.Copy /> کپی
            </button>
            <button onClick={clearLogs} className="text-[10px] px-2 py-1 rounded-lg flex items-center gap-1" style={styles.btn("#64748b")}>
              <Icon.Trash /> پاک
            </button>
          </div>
        </div>
        <div ref={logsRef} className="h-52 overflow-y-auto p-4 space-y-0.5 font-mono text-xs" style={{ background: "#02060f" }}>
          {logs.length === 0
            ? <span style={{ color: "#1e3a5f" }}>// در انتظار لاگ...</span>
            : logs.map((log, i) => {
              const color = log.includes("✅") ? "#4ade80"
                : log.includes("❌") || log.includes("⚠️") ? "#f87171"
                  : log.includes("429") ? "#fb923c"
                    : log.includes("⚔️") || log.includes("📈") || log.includes("💰") ? "#38bdf8"
                      : "#475569";
              return <div key={i} style={{ color, lineHeight: 1.6 }}>{log}</div>;
            })}
        </div>
      </div>
    </div>
  );

  const renderProducts = () => (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap gap-3 items-center" style={styles.card && { padding: "16px 20px", ...styles.card }}>
        {/* Search */}
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl flex-1" style={{ background: "#0a1628", border: "1px solid #162040", minWidth: 180 }}>
          <Icon.Search />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="جستجو در محصولات..." className="bg-transparent text-sm outline-none flex-1"
            style={{ color: "#e2e8f0" }} />
        </div>
        {/* Filters */}
        <div className="flex gap-1.5">
          {([["all", "همه"], ["winning", "برنده"], ["losing", "بازنده"], ["configured", "تنظیم‌شده"], ["unconfigured", "بدون config"]] as [FilterMode, string][]).map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)}
              className="text-xs px-3 py-1.5 rounded-full font-medium"
              style={{
                background: filter === k ? "rgba(99,102,241,0.2)" : "transparent",
                border: `1px solid ${filter === k ? "#6366f1" : "#0f1f3d"}`,
                color: filter === k ? "#a5b4fc" : "#475569",
              }}>{l}</button>
          ))}
        </div>
        <div className="flex-1" />
        {/* Sort */}
        <select value={sortBy} onChange={e => setSortBy(e.target.value as any)}
          className="text-xs px-3 py-2 rounded-xl"
          style={{ background: "#0a1628", border: "1px solid #162040", color: "#94a3b8" }}>
          <option value="none">ترتیب پیش‌فرض</option>
          <option value="price">قیمت</option>
          <option value="stock">موجودی</option>
          <option value="title">نام</option>
        </select>
        <button onClick={() => setSortDir(d => d === "asc" ? "desc" : "asc")}
          className="text-xs px-3 py-2 rounded-xl"
          style={{ background: "#0a1628", border: "1px solid #162040", color: "#94a3b8" }}>
          {sortDir === "asc" ? "↑ صعودی" : "↓ نزولی"}
        </button>
        {/* Actions */}
        <button onClick={loadProducts} disabled={loading}
          className="flex items-center gap-2 text-sm px-4 py-2 rounded-xl font-medium"
          style={styles.btn("#38bdf8")}>
          <Icon.Refresh />{loading ? "دریافت..." : "دریافت"}
        </button>
        <button onClick={saveConfigs} disabled={saving}
          className="flex items-center gap-2 text-sm px-4 py-2 rounded-xl font-medium"
          style={styles.btn("#4ade80")}>
          <Icon.Save />{saving ? "ذخیره..." : "ذخیره"}
        </button>
      </div>

      {/* Bulk actions bar (when something selected) */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 px-5 py-3 rounded-xl border" style={{ background: "rgba(99,102,241,0.08)", borderColor: "#6366f133" }}>
          <span className="text-xs font-medium" style={{ color: "#a5b4fc" }}>{selectedIds.size} انتخاب شده</span>
          <div className="flex items-center gap-2 mr-auto">
            <input type="number" value={bulkMin} onChange={e => setBulkMin(e.target.value)}
              placeholder="کف جمعی" className="w-28 px-3 py-1.5 text-xs text-center"
              style={styles.input} />
            <input type="number" value={bulkMax} onChange={e => setBulkMax(e.target.value)}
              placeholder="سقف جمعی" className="w-28 px-3 py-1.5 text-xs text-center"
              style={styles.input} />
            <button onClick={applyBulkPrices}
              className="text-xs px-4 py-1.5 rounded-lg font-semibold"
              style={styles.btn("#a5b4fc")}>اعمال</button>
            <button onClick={() => setSelectedIds(new Set())}
              className="text-xs px-3 py-1.5 rounded-lg"
              style={styles.btn("#f87171")}>لغو</button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl overflow-hidden border" style={styles.card}>
        <div className="overflow-x-auto">
          <table style={styles.table}>
            <thead>
              <tr style={{ borderBottom: "1px solid #0f1f3d", background: "rgba(15,23,42,0.5)" }}>
                <th className="p-3 text-right">
                  <input type="checkbox" checked={selectedIds.size === filtered.length && filtered.length > 0}
                    onChange={selectAll} className="w-3.5 h-3.5 rounded" />
                </th>
                {["وضعیت", "فعال", "کد", "نام محصول", "قیمت جاری", "مرجع", "موجودی", "کف ▼", "سقف ▲", "عملیات"].map(h => (
                  <th key={h} className="p-3 text-right text-[11px] font-semibold" style={{ color: "#334155" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={11} className="text-center py-20 text-sm" style={{ color: "#1e3a5f" }}>
                    {products.length === 0 ? "ابتدا محصولات را دریافت کنید" : "موردی یافت نشد"}
                  </td>
                </tr>
              ) : filtered.map(p => {
                const isDisc = discoveringId === String(p.variant_id);
                const isToggling = togglingId === String(p.variant_id);
                const isActive = p.is_active !== false; // default true
                return (
                  <tr key={p.variant_id}
                    style={{ borderBottom: "1px solid #0a1220", opacity: isActive ? 1 : 0.45 }}
                    className="transition-colors hover:bg-slate-900/40">
                    <td className="p-3">
                      <input type="checkbox" checked={selectedIds.has(p.variant_id)}
                        onChange={() => setSelectedIds(prev => {
                          const s = new Set(prev);
                          s.has(p.variant_id) ? s.delete(p.variant_id) : s.add(p.variant_id);
                          return s;
                        })} className="w-3.5 h-3.5 rounded" />
                    </td>
                    <td className="p-3"><Badge win={p.is_buy_box_winner} /></td>
                    <td className="p-3">
                      <button onClick={() => !isToggling && toggleVariantActive(p.variant_id, isActive)}
                        disabled={isToggling} className="transition-opacity" style={{ opacity: isToggling ? 0.5 : 1 }}>
                        <Icon.Toggle on={isActive} />
                      </button>
                    </td>
                    <td className="p-3 font-mono text-[11px]" style={{ color: "#334155" }}>{p.variant_id}</td>
                    <td className="p-3" style={{ maxWidth: 220 }}>
                      <span className="text-xs block truncate" style={{ color: "#94a3b8" }} title={p.title}>{p.title}</span>
                    </td>
                    <td className="p-3 font-mono text-sm font-bold" style={{ color: "#38bdf8" }}>{fmtNum(p.current_price)}</td>
                    <td className="p-3 font-mono text-xs" style={{ color: "#334155" }}>{fmtNum(p.reference_price)}</td>
                    <td className="p-3 text-xs font-mono" style={{ color: "#475569" }}>
                      {fmtNum(p.seller_stock ?? p.stock)}
                    </td>
                    <td className="p-3">
                      <input type="number" value={p.min_price} disabled={isDisc}
                        onChange={e => handlePriceChange(p.variant_id, "min_price", e.target.value)}
                        placeholder="کف" className="w-28 px-2 py-1.5 text-xs text-center"
                        style={{ ...styles.input, opacity: isDisc ? 0.4 : 1 }} />
                    </td>
                    <td className="p-3">
                      <input type="number" value={p.max_price} disabled={isDisc}
                        onChange={e => handlePriceChange(p.variant_id, "max_price", e.target.value)}
                        placeholder="سقف" className="w-28 px-2 py-1.5 text-xs text-center"
                        style={{ ...styles.input, opacity: isDisc ? 0.4 : 1 }} />
                    </td>
                    <td className="p-3">
                      <button onClick={() => autoDiscover(p.variant_id, p.reference_price, p.current_price)}
                        disabled={isDisc || !p.current_price}
                        className="flex items-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-lg"
                        style={{ background: "rgba(99,102,241,0.12)", border: "1px solid #6366f133", color: "#a5b4fc", opacity: isDisc || !p.current_price ? 0.4 : 1 }}>
                        {isDisc ? <span className="animate-pulse">اسکن...</span> : <><Icon.Zap /> کشف</>}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-2.5 border-t text-xs flex items-center gap-3" style={{ borderColor: "#0f1f3d", color: "#334155" }}>
          نمایش {filtered.length} از {products.length} محصول
          {selectedIds.size > 0 && <span style={{ color: "#6366f1" }}>— {selectedIds.size} انتخاب‌شده</span>}
        </div>
      </div>
    </div>
  );

  const renderSettings = () => {
    const BUYBOX_PRESETS = [
      { label: "یک گام زیر رقیب", formula: "competitor_price - step_price" },
      { label: "۱٪ زیر رقیب", formula: "competitor_price * 0.99" },
      { label: "دو گام زیر رقیب", formula: "competitor_price - step_price * 2" },
      { label: "زیر رقیب ≥ کف", formula: "max(competitor_price - step_price, min_price)" },
    ];
    const MIN_PRESETS = [
      { label: "۷۵٪ مرجع", formula: "reference_price * 0.75" },
      { label: "۸۰٪ مرجع", formula: "reference_price * 0.80" },
      { label: "۷۰٪ مرجع", formula: "reference_price * 0.70" },
      { label: "هزینه+۲۰٪", formula: "cost * 1.20" },
    ];
    const FORMULA_VARS_BB = ["competitor_price", "reference_price", "current_price", "step_price", "min_price", "buy_box_price"];
    const FORMULA_VARS_MIN = ["reference_price", "current_price", "step_price", "cost"];

    const set = (k: keyof Settings) => (v: any) => setSettings(s => ({ ...s, [k]: v }));

    return (
      <div className="space-y-5 max-w-3xl">
        {/* Strategy */}
        <div className="rounded-2xl p-5 space-y-4 border" style={styles.card}>
          <h3 className="text-sm font-bold" style={{ color: "#94a3b8" }}>استراتژی رقابت</h3>
          <div className="grid grid-cols-3 gap-2">
            {[
              { k: "aggressive", l: "تهاجمی", d: "همیشه یک گام زیر رقیب" },
              { k: "conservative", l: "محافظه‌کار", d: "فقط وقتی فاصله بزرگ باشد" },
              { k: "formula", l: "فرمول‌محور", d: "بر اساس فرمول سفارشی" },
            ].map(s => (
              <button key={s.k} onClick={() => set("strategy_mode")(s.k)}
                className="p-3 rounded-xl border text-right transition-all"
                style={{
                  background: settings.strategy_mode === s.k ? "rgba(99,102,241,0.15)" : "#0a1628",
                  borderColor: settings.strategy_mode === s.k ? "#6366f1" : "#162040",
                  color: settings.strategy_mode === s.k ? "#a5b4fc" : "#475569",
                }}>
                <div className="font-semibold text-sm">{s.l}</div>
                <div className="text-[10px] mt-1 opacity-70">{s.d}</div>
              </button>
            ))}
          </div>

          <div className={settings.strategy_mode !== "formula" ? "opacity-40 pointer-events-none" : ""}>
            <FormulaInput label="فرمول قیمت بای‌باکس" hint="وقتی بای‌باکس نداریم، قیمت هدف را محاسبه می‌کند"
              value={settings.buybox_formula} onChange={set("buybox_formula")}
              variables={FORMULA_VARS_BB} presets={BUYBOX_PRESETS}
              onTest={() => testFormula("buybox", settings.buybox_formula)} testResult={buyboxTestResult} />
          </div>
        </div>

        {/* Min price formula */}
        <div className="rounded-2xl p-5 space-y-4 border" style={styles.card}>
          <h3 className="text-sm font-bold" style={{ color: "#94a3b8" }}>فرمول کف قیمت دسته‌جمعی</h3>
          <FormulaInput label="فرمول کف قیمت" hint="برای محاسبه خودکار کف قیمت همه محصولات"
            value={settings.min_price_formula} onChange={set("min_price_formula")}
            variables={FORMULA_VARS_MIN} presets={MIN_PRESETS}
            onTest={() => testFormula("min_price", settings.min_price_formula)} testResult={minPriceTestResult} />
          <div className="flex items-center gap-3">
            <button onClick={applyMinFormula} disabled={applyingFormula || !settings.min_price_formula}
              className="text-xs px-4 py-2 rounded-xl font-semibold"
              style={{ ...styles.btn("#c084fc"), opacity: applyingFormula || !settings.min_price_formula ? 0.4 : 1 }}>
              {applyingFormula ? "در حال اعمال..." : "اعمال به همه محصولات"}
            </button>
            <p className="text-[10px]" style={{ color: "#334155" }}>قیمت دیجی‌کالا تغییر نمی‌کند — فقط config ذخیره می‌شود</p>
          </div>
        </div>

        {/* Advanced settings */}
        <div className="rounded-2xl p-5 space-y-5 border" style={styles.card}>
          <h3 className="text-sm font-bold" style={{ color: "#94a3b8" }}>تنظیمات پیشرفته</h3>

          {/* Guard rails */}
          <div className="grid grid-cols-2 gap-4">
            {[
              { k: "variant_cooldown_seconds", l: "Cooldown هر تنوع (ثانیه)", type: "number" },
              { k: "max_price_change_percent", l: "حداکثر تغییر قیمت (%)", type: "number", step: 0.5 },
              { k: "max_consecutive_failures", l: "حداکثر خطای متوالی", type: "number" },
              { k: "rate_limit_pause_seconds", l: "مکث بعد از 429 (ثانیه)", type: "number" },
            ].map(f => (
              <div key={f.k} className="space-y-1">
                <label className="text-[11px]" style={{ color: "#475569" }}>{f.l}</label>
                <input type={f.type} value={(settings as any)[f.k]} step={(f as any).step || 1}
                  onChange={e => set(f.k as keyof Settings)(Number(e.target.value))}
                  className="w-full px-3 py-2 text-sm" style={styles.input} />
              </div>
            ))}
          </div>

          {/* Timing */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { k: "request_delay_min", l: "تاخیر کمینه (ثانیه)", step: 0.5 },
              { k: "request_delay_max", l: "تاخیر بیشینه (ثانیه)", step: 0.5 },
              { k: "rate_limit_backoff_base", l: "پایه backoff 429", step: 5 },
            ].map(f => (
              <div key={f.k} className="space-y-1">
                <label className="text-[11px]" style={{ color: "#475569" }}>{f.l}</label>
                <input type="number" value={(settings as any)[f.k]} step={f.step}
                  onChange={e => set(f.k as keyof Settings)(Number(e.target.value))}
                  className="w-full px-3 py-2 text-sm" style={styles.input} />
              </div>
            ))}
          </div>

          {/* Delivery */}
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1">
              <label className="text-[11px]" style={{ color: "#475569" }}>مدت تحویل (روز)</label>
              <input type="number" min={1} value={settings.lead_time}
                onChange={e => set("lead_time")(Number(e.target.value))}
                className="w-full px-3 py-2 text-sm" style={styles.input} />
            </div>
            <div className="space-y-1">
              <label className="text-[11px]" style={{ color: "#475569" }}>حداکثر سفارش</label>
              <input type="number" min={1} value={settings.max_per_order}
                onChange={e => set("max_per_order")(Number(e.target.value))}
                className="w-full px-3 py-2 text-sm" style={styles.input} />
            </div>
            <div className="space-y-1">
              <label className="text-[11px]" style={{ color: "#475569" }}>نوع ارسال</label>
              <select value={settings.shipping_type} onChange={e => set("shipping_type")(e.target.value)}
                className="w-full px-3 py-2 text-sm" style={styles.input}>
                <option value="seller">فروشنده</option>
                <option value="digikala">دیجی‌کالا</option>
              </select>
            </div>
          </div>

          {/* Toggles */}
          <div className="flex gap-6">
            <label className="flex items-center gap-3 cursor-pointer">
              <button onClick={() => set("dry_run")(!settings.dry_run)}>
                <Icon.Toggle on={settings.dry_run} />
              </button>
              <div>
                <div className="text-xs font-semibold" style={{ color: "#94a3b8" }}>حالت آزمایشی (Dry Run)</div>
                <div className="text-[10px]" style={{ color: "#334155" }}>قیمت ارسال نمی‌شود</div>
              </div>
            </label>
          </div>

          {/* Webhook */}
          <div className="space-y-1">
            <label className="text-[11px]" style={{ color: "#475569" }}>Webhook هشدار (اختیاری)</label>
            <input type="url" value={settings.notify_webhook_url} dir="ltr"
              onChange={e => set("notify_webhook_url")(e.target.value)}
              placeholder="https://hooks.slack.com/..."
              className="w-full px-3 py-2 text-sm font-mono" style={styles.input} />
          </div>

          <div className="flex justify-end pt-2">
            <button onClick={saveSettings} disabled={savingSettings}
              className="flex items-center gap-2 text-sm font-bold px-6 py-2.5 rounded-xl"
              style={styles.btn("#4ade80")}>
              <Icon.Save />{savingSettings ? "در حال ذخیره..." : "ذخیره تنظیمات"}
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderLogs = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-semibold" style={{ color: "#94a3b8" }}>لاگ‌های زنده</h3>
        <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "#0a1628", color: "#475569" }}>
          {logs.length} خط
        </span>
        <div className="flex gap-2 mr-auto">
          <button onClick={copyLog} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg" style={styles.btn("#64748b")}>
            <Icon.Copy /> کپی
          </button>
          <button onClick={clearLogs} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg" style={styles.btn("#f87171")}>
            <Icon.Trash /> پاک
          </button>
        </div>
      </div>
      <div className="rounded-2xl overflow-hidden border" style={{ ...styles.card, background: "#02060f" }}>
        <div ref={logsRef} className="h-[calc(100vh-240px)] overflow-y-auto p-5 space-y-0.5 font-mono text-xs">
          {logs.length === 0
            ? <span style={{ color: "#1e3a5f" }}>// در انتظار لاگ...</span>
            : logs.map((log, i) => {
              const color = log.includes("✅") ? "#4ade80"
                : log.includes("❌") ? "#f87171"
                  : log.includes("⚠️") ? "#fbbf24"
                    : log.includes("429") ? "#fb923c"
                      : log.includes("⚔️") || log.includes("📈") || log.includes("💰") ? "#38bdf8"
                        : log.includes("━━") ? "#1e3a5f"
                          : "#334155";
              return (
                <div key={i} style={{ color, lineHeight: 1.7 }}>{log}</div>
              );
            })}
        </div>
      </div>
    </div>
  );

  // ─── Layout ────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen overflow-hidden" dir="rtl" style={{ fontFamily: "'Vazirmatn', 'Tahoma', sans-serif", ...styles.main }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #162040; border-radius: 4px; }
        @keyframes toastIn { from { opacity:0; transform: translateY(-8px) scale(0.97); } to { opacity:1; transform: none; } }
        input[type=number]::-webkit-inner-spin-button { opacity:0.3; }
        select option { background: #0a1628; }
      `}</style>

      <ToastContainer toasts={toasts} remove={removeToast} />

      {/* Sidebar */}
      <aside className="flex flex-col py-6 gap-1" style={styles.sidebar}>
        {/* Logo */}
        <div className="px-5 mb-6">
          <div className="text-lg font-bold tracking-tight" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
            <span style={{ color: "#38bdf8" }}>DK</span>
            <span style={{ color: "#334155" }}>_</span>
            <span style={{ color: "#475569" }}>Repricer</span>
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: "#1e3a5f" }}>v4.0 — production</div>
        </div>

        {/* Nav */}
        {navItems.map(item => (
          <button key={item.id} onClick={() => setTab(item.id)}
            className="flex items-center gap-3 mx-3 px-4 py-2.5 rounded-xl text-sm font-medium text-right transition-all"
            style={{
              background: tab === item.id ? "rgba(56,189,248,0.1)" : "transparent",
              color: tab === item.id ? "#38bdf8" : "#334155",
              borderLeft: tab === item.id ? "2px solid #38bdf8" : "2px solid transparent",
            }}>
            <item.Icon />
            {item.label}
          </button>
        ))}

        {/* Workspace select */}
        <div className="mt-auto px-4 space-y-1">
          <label className="text-[10px]" style={{ color: "#1e3a5f" }}>Workspace</label>
          <input type="number" value={workspaceId} min={1}
            onChange={e => setWorkspaceId(Number(e.target.value))}
            className="w-full px-3 py-1.5 text-xs text-center rounded-lg"
            style={{ background: "#040b18", border: "1px solid #0f1f3d", color: "#334155" }} />
        </div>

        {/* Bot status badge */}
        <div className="mx-4 mt-2 px-3 py-2 rounded-xl flex items-center gap-2"
          style={{ background: isRunning ? "rgba(34,197,94,0.06)" : "#040b18", border: `1px solid ${isRunning ? "#22c55e22" : "#0f1f3d"}` }}>
          <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? "bg-green-400 animate-pulse" : "bg-slate-700"}`} />
          <span className="text-[10px] font-medium" style={{ color: isRunning ? "#4ade80" : "#1e3a5f" }}>
            {isRunning ? `چرخه #${botState.cycle_count || 0}` : "متوقف"}
          </span>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-7">
        {/* Page header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-lg font-bold" style={{ color: "#e2e8f0" }}>
              {navItems.find(n => n.id === tab)?.label}
            </h1>
            <p className="text-xs mt-0.5" style={{ color: "#334155" }}>
              {tab === "dashboard" && "نمای کلی سیستم قیمت‌گذاری"}
              {tab === "products" && `${products.length} محصول فعال | ${configured} تنظیم‌شده`}
              {tab === "settings" && "پیکربندی پیشرفته ربات"}
              {tab === "logs" && "لاگ‌های زنده سیستم"}
            </p>
          </div>
        </div>

        {tab === "dashboard" && renderDashboard()}
        {tab === "products" && renderProducts()}
        {tab === "settings" && renderSettings()}
        {tab === "logs" && renderLogs()}
      </main>
    </div>
  );
}