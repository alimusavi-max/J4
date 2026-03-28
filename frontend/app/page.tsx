"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ─── Helpers ────────────────────────────────────────────────────────────────
const fmt    = (n: any) => n ? Number(n).toLocaleString("fa-IR") : "—";
const fmtNum = (n: any) => n ? Number(n).toLocaleString()        : "—";

// ─── Types ───────────────────────────────────────────────────────────────────
interface Product {
  variant_id:       number;
  title:            string;
  is_buy_box_winner: boolean;
  current_price:    number;
  reference_price:  number;
  buy_box_price?:   number;
  stock:            number;
  min_price:        string | number;
  max_price:        string | number;
  has_config:       boolean;
}

interface BotState {
  is_running?:      boolean;
  workspace_id?:    number;
  step_price?:      number;
  started_at?:      string;
  cycle_count?:     number;
  total_updates?:   number;
  buybox_wins?:     number;
  rate_limit_hits?: number;
}

interface Settings {
  lead_time:               number;
  shipping_type:           string;
  max_per_order:           number;
  request_delay_min:       number;
  request_delay_max:       number;
  rate_limit_backoff_base: number;
  max_retries:             number;
  buybox_formula:          string;
  min_price_formula:       string;
  auto_apply_min_price:    boolean;
  strategy_mode:           string;
}

const DEFAULT_SETTINGS: Settings = {
  lead_time:               2,
  shipping_type:           "seller",
  max_per_order:           4,
  request_delay_min:       3.0,
  request_delay_max:       6.0,
  rate_limit_backoff_base: 15,
  max_retries:             3,
  buybox_formula:          "competitor_price - step_price",
  min_price_formula:       "",
  auto_apply_min_price:    false,
  strategy_mode:           "aggressive",
};

// ─── StatCard ────────────────────────────────────────────────────────────────
function StatCard({
  label, value, sub, color = "cyan", pulse = false,
}: {
  label: string; value: any; sub?: string; color?: string; pulse?: boolean;
}) {
  const colors: Record<string, string> = {
    cyan:   "from-cyan-500/20   to-cyan-600/5   border-cyan-500/30   text-cyan-300",
    green:  "from-green-500/20  to-green-600/5  border-green-500/30  text-green-300",
    amber:  "from-amber-500/20  to-amber-600/5  border-amber-500/30  text-amber-300",
    red:    "from-red-500/20    to-red-600/5    border-red-500/30    text-red-300",
    violet: "from-violet-500/20 to-violet-600/5 border-violet-500/30 text-violet-300",
    rose:   "from-rose-500/20   to-rose-600/5   border-rose-500/30   text-rose-300",
  };
  return (
    <div className={`relative bg-gradient-to-br ${colors[color] || colors.cyan} border rounded-xl p-4 overflow-hidden`}>
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
        </span>
      )}
      <div className="text-2xl font-bold font-mono tracking-tight">{value}</div>
      <div className="text-xs text-slate-400 mt-1">{label}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

// ─── FormulaInput ────────────────────────────────────────────────────────────
function FormulaInput({
  value, onChange, placeholder, variables,
  onTest, testResult, presets, label, hint,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  variables: string[];
  onTest: () => void;
  testResult: { success?: boolean; result?: number; error?: string } | null;
  presets: { label: string; formula: string }[];
  label: string;
  hint: string;
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold text-slate-300">{label}</label>
      <p className="text-[10px] text-slate-500">{hint}</p>

      {/* Preset picker */}
      <div className="flex flex-wrap gap-1.5">
        {presets.map((p) => (
          <button
            key={p.formula}
            onClick={() => onChange(p.formula)}
            className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${
              value === p.formula
                ? "bg-cyan-700/50 border-cyan-500/60 text-cyan-200"
                : "bg-slate-800 border-slate-600 text-slate-400 hover:text-slate-200"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Formula textarea */}
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          dir="ltr"
          className="flex-1 bg-slate-900 border border-slate-600 focus:border-cyan-500 text-slate-200 rounded-lg px-3 py-2 text-sm font-mono outline-none transition-colors placeholder-slate-600"
        />
        <button
          onClick={onTest}
          className="bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-300 text-xs px-3 py-2 rounded-lg whitespace-nowrap transition-colors"
        >
          🧪 تست
        </button>
      </div>

      {/* Variables */}
      <div className="flex flex-wrap gap-1">
        {variables.map((v) => (
          <code
            key={v}
            onClick={() => onChange((value ? value + " " : "") + v)}
            className="text-[10px] bg-slate-800/80 border border-slate-700 text-cyan-400 px-1.5 py-0.5 rounded cursor-pointer hover:bg-slate-700 transition-colors"
          >
            {v}
          </code>
        ))}
      </div>

      {/* Test result */}
      {testResult && (
        <div
          className={`text-xs px-3 py-2 rounded-lg border ${
            testResult.success
              ? "bg-emerald-900/30 border-emerald-700/40 text-emerald-300"
              : "bg-red-900/30 border-red-700/40 text-red-300"
          }`}
        >
          {testResult.success
            ? `✅ نتیجه: ${fmtNum(testResult.result)} تومان`
            : `❌ ${testResult.error}`}
        </div>
      )}
    </div>
  );
}

// ─── SettingsPanel ────────────────────────────────────────────────────────────
function SettingsPanel({
  settings, onChange, onSave, saving,
  onApplyMinFormula, applyingFormula, workspaceId, stepPrice,
}: {
  settings: Settings;
  onChange: (s: Settings) => void;
  onSave:   () => void;
  saving:   boolean;
  onApplyMinFormula: () => void;
  applyingFormula:   boolean;
  workspaceId: number;
  stepPrice:   number;
}) {
  const [buyboxTestResult,   setBuyboxTestResult]   = useState<any>(null);
  const [minPriceTestResult, setMinPriceTestResult] = useState<any>(null);

  const FORMULA_VARS_BUYBOX    = ["competitor_price", "reference_price", "current_price", "step_price", "min_price", "buy_box_price"];
  const FORMULA_VARS_MIN_PRICE = ["reference_price", "current_price", "step_price", "cost"];

  const BUYBOX_PRESETS = [
    { label: "یک گام زیر رقیب",      formula: "competitor_price - step_price" },
    { label: "یک درصد زیر رقیب",     formula: "competitor_price * 0.99" },
    { label: "دو گام زیر رقیب",      formula: "competitor_price - step_price * 2" },
    { label: "زیر رقیب ≥ کف",        formula: "max(competitor_price - step_price, min_price)" },
  ];
  const MIN_PRICE_PRESETS = [
    { label: "۷۵٪ مرجع",  formula: "reference_price * 0.75" },
    { label: "۸۰٪ مرجع",  formula: "reference_price * 0.80" },
    { label: "۷۰٪ مرجع",  formula: "reference_price * 0.70" },
    { label: "هزینه+۲۰٪", formula: "cost * 1.20" },
  ];

  const testFormula = async (type: "buybox" | "min_price", formula: string) => {
    const sampleValues =
      type === "buybox"
        ? { competitor_price: 100000, reference_price: 150000, current_price: 98000, step_price: stepPrice, min_price: 70000, buy_box_price: 95000 }
        : { reference_price: 150000, current_price: 98000, step_price: stepPrice, cost: 60000 };

    try {
      const res = await fetch(`${API}/api/formula/test`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ formula, formula_type: type, sample_values: sampleValues }),
      });
      const data = await res.json();
      if (type === "buybox")    setBuyboxTestResult(data);
      else                      setMinPriceTestResult(data);
    } catch {
      const err = { success: false, error: "خطا در ارتباط با سرور" };
      if (type === "buybox") setBuyboxTestResult(err);
      else                   setMinPriceTestResult(err);
    }
  };

  const set = (key: keyof Settings) => (val: any) => onChange({ ...settings, [key]: val });

  const STRATEGIES = [
    {
      key: "aggressive",
      label: "تهاجمی",
      desc: "همیشه یک گام زیر ارزان‌ترین رقیب — حداکثر شانس BuyBox",
    },
    {
      key: "conservative",
      label: "محافظه‌کار",
      desc: "فقط اگر فاصله قیمتی بزرگ باشد وارد رقابت می‌شود",
    },
    {
      key: "formula",
      label: "فرمول‌محور",
      desc: "قیمت هدف دقیقاً از فرمول سفارشی محاسبه می‌شود",
    },
  ];

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-6 backdrop-blur-sm">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-slate-200">⚙️ تنظیمات پیشرفته ربات</h2>
      </div>

      {/* ── Strategy Mode ── */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-slate-300">استراتژی رقابت</label>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {STRATEGIES.map((s) => (
            <button
              key={s.key}
              onClick={() => set("strategy_mode")(s.key)}
              className={`text-right p-3 rounded-xl border transition-all ${
                settings.strategy_mode === s.key
                  ? "bg-cyan-700/30 border-cyan-500/60 text-cyan-200"
                  : "bg-slate-900/50 border-slate-700 text-slate-400 hover:border-slate-500"
              }`}
            >
              <div className="font-semibold text-sm">{s.label}</div>
              <div className="text-[10px] mt-1 opacity-70 leading-4">{s.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* ── BuyBox Formula ── */}
      <div className={`transition-opacity ${settings.strategy_mode !== "formula" ? "opacity-50 pointer-events-none" : ""}`}>
        <FormulaInput
          label="🎯 فرمول قیمت‌گذاری بای‌باکس"
          hint="فرمولی برای محاسبه قیمت رقابتی وقتی بای‌باکس نداریم."
          value={settings.buybox_formula}
          onChange={set("buybox_formula")}
          placeholder="مثال: competitor_price - step_price"
          variables={FORMULA_VARS_BUYBOX}
          presets={BUYBOX_PRESETS}
          onTest={() => testFormula("buybox", settings.buybox_formula)}
          testResult={buyboxTestResult}
        />
        {settings.strategy_mode !== "formula" && (
          <p className="text-[10px] text-slate-500 mt-1">⚠️ فرمول فقط در حالت «فرمول‌محور» فعال است</p>
        )}
      </div>

      {/* ── Min Price Formula ── */}
      <div className="space-y-3 border-t border-slate-700/40 pt-4">
        <FormulaInput
          label="📉 فرمول محاسبه خودکار کف قیمت"
          hint="با این فرمول می‌توانید کف قیمت همه محصولات را به صورت دسته‌ای محاسبه و اعمال کنید."
          value={settings.min_price_formula}
          onChange={set("min_price_formula")}
          placeholder="مثال: reference_price * 0.75"
          variables={FORMULA_VARS_MIN_PRICE}
          presets={MIN_PRICE_PRESETS}
          onTest={() => testFormula("min_price", settings.min_price_formula)}
          testResult={minPriceTestResult}
        />
        <div className="flex items-center gap-3">
          <button
            onClick={onApplyMinFormula}
            disabled={applyingFormula || !settings.min_price_formula}
            className="bg-indigo-700/70 hover:bg-indigo-600/70 border border-indigo-600/50 text-indigo-200 text-xs font-semibold px-4 py-2 rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {applyingFormula ? "⏳ در حال اعمال..." : "📐 اعمال به همه محصولات"}
          </button>
          <p className="text-[10px] text-slate-500">
            کف قیمت محاسبه‌شده در config ذخیره می‌شود — قیمت دیجی‌کالا فوراً تغییر نمی‌کند
          </p>
        </div>
      </div>

      {/* ── API Settings ── */}
      <div className="border-t border-slate-700/40 pt-4 space-y-3">
        <label className="text-xs font-semibold text-slate-300">🔧 تنظیمات API و تحویل</label>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { key: "lead_time",     label: "مدت تحویل (روز)",     step: 1,   min: 1 },
            { key: "max_per_order", label: "حداکثر سفارش",        step: 1,   min: 1 },
          ].map(({ key, label, step, min }) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500">{label}</label>
              <input
                type="number"
                value={(settings as any)[key]}
                step={step}
                min={min}
                onChange={(e) => set(key as keyof Settings)(Number(e.target.value))}
                className="bg-slate-900 border border-slate-600 focus:border-cyan-500 text-slate-200 rounded-lg px-3 py-2 text-sm text-center outline-none"
              />
            </div>
          ))}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-slate-500">نوع ارسال</label>
            <select
              value={settings.shipping_type}
              onChange={(e) => set("shipping_type")(e.target.value)}
              className="bg-slate-900 border border-slate-600 focus:border-cyan-500 text-slate-200 rounded-lg px-3 py-2 text-sm outline-none"
            >
              <option value="seller">فروشنده</option>
              <option value="digikala">دیجی‌کالا</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-slate-500">تلاش مجدد</label>
            <input
              type="number" min={1} max={5}
              value={settings.max_retries}
              onChange={(e) => set("max_retries")(Number(e.target.value))}
              className="bg-slate-900 border border-slate-600 focus:border-cyan-500 text-slate-200 rounded-lg px-3 py-2 text-sm text-center outline-none"
            />
          </div>
        </div>

        <label className="text-xs font-semibold text-slate-300 block mt-2">⏱ مدیریت تاخیر و نرخ (ثانیه)</label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {[
            { key: "request_delay_min",       label: "تاخیر کمینه",       step: 0.5 },
            { key: "request_delay_max",       label: "تاخیر بیشینه",      step: 0.5 },
            { key: "rate_limit_backoff_base", label: "صبر پس از 429",     step: 5   },
          ].map(({ key, label, step }) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500">{label}</label>
              <input
                type="number"
                value={(settings as any)[key]}
                step={step}
                min={0}
                onChange={(e) => set(key as keyof Settings)(Number(e.target.value))}
                className="bg-slate-900 border border-slate-600 focus:border-cyan-500 text-slate-200 rounded-lg px-3 py-2 text-sm text-center outline-none"
              />
            </div>
          ))}
        </div>
        <p className="text-[10px] text-slate-500">
          تاخیر تصادفی بین درخواست‌ها (min–max) برای شبیه‌سازی رفتار انسانی — در صورت 429 به صورت نمایی افزایش می‌یابد
        </p>
      </div>

      {/* ── Save ── */}
      <div className="flex justify-end pt-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="bg-emerald-700/80 hover:bg-emerald-600 border border-emerald-600/50 text-white text-sm font-bold px-6 py-2.5 rounded-lg transition-all disabled:opacity-50"
        >
          {saving ? "⏳ ذخیره..." : "💾 ذخیره تنظیمات"}
        </button>
      </div>
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [products,       setProducts]       = useState<Product[]>([]);
  const [logs,           setLogs]           = useState<string[]>([]);
  const [botState,       setBotState]       = useState<BotState>({});
  const [isRunning,      setIsRunning]      = useState(false);
  const [loading,        setLoading]        = useState(false);
  const [saving,         setSaving]         = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [stepPrice,      setStepPrice]      = useState(1000);
  const [cycleDelay,     setCycleDelay]     = useState(120);
  const [workspaceId,    setWorkspaceId]    = useState(1);
  const [filter,         setFilter]         = useState("all");
  const [discoveringId,  setDiscoveringId]  = useState<string | null>(null);
  const [showSettings,   setShowSettings]   = useState(false);
  const [settings,       setSettings]       = useState<Settings>(DEFAULT_SETTINGS);
  const [applyingFormula, setApplyingFormula] = useState(false);
  const [stats,          setStats]          = useState({ total: 0, configured: 0 });
  const logsRef = useRef<HTMLDivElement>(null);

  // ─── Load Settings ────────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then((r) => r.json())
      .then((d) => { if (d.settings) setSettings(d.settings); })
      .catch(() => {});
  }, []);

  // ─── Polling ─────────────────────────────────────────────────────
  useEffect(() => {
    const poll = setInterval(() => {
      fetch(`${API}/api/logs?limit=150`)
        .then((r) => r.json())
        .then((d) => {
          setLogs(d.logs || []);
          setIsRunning(d.is_running);
          setBotState(d.bot_state || {});
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = 0;
  }, [logs]);

  // ─── Actions ──────────────────────────────────────────────────────
  const loadProducts = async () => {
    setLoading(true);
    try {
      const res  = await fetch(`${API}/api/products?workspace_id=${workspaceId}`);
      const data = await res.json();
      setProducts(data.variants || []);
      setStats({ total: data.total || 0, configured: data.configured || 0 });
    } catch {
      alert("خطا در ارتباط با سرور");
    }
    setLoading(false);
  };

  const saveConfigs = async () => {
    setSaving(true);
    const configs: Record<string, any> = {};
    products.forEach((p) => {
      if (p.min_price !== "" && p.max_price !== "") {
        configs[String(p.variant_id)] = {
          min_price: parseInt(String(p.min_price)),
          max_price: parseInt(String(p.max_price)),
        };
      }
    });
    try {
      const res  = await fetch(`${API}/api/config`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ configs }),
      });
      const d = await res.json();
      alert(`✅ ${d.saved_count} محصول ذخیره شد.`);
    } catch {
      alert("خطا در ذخیره‌سازی");
    }
    setSaving(false);
  };

  const saveSettings = async () => {
    setSavingSettings(true);
    try {
      const res  = await fetch(`${API}/api/settings`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(settings),
      });
      const data = await res.json();
      if (data.status === "success") alert("✅ تنظیمات ذخیره شد.");
      else                           alert("❌ خطا: " + JSON.stringify(data));
    } catch {
      alert("خطا در ارتباط با سرور");
    }
    setSavingSettings(false);
  };

  const applyMinFormula = async () => {
    if (!settings.min_price_formula) {
      alert("ابتدا یک فرمول کف قیمت وارد کنید.");
      return;
    }
    if (!confirm(`فرمول «${settings.min_price_formula}» به همه محصولات اعمال شود؟`)) return;

    setApplyingFormula(true);
    try {
      const res  = await fetch(`${API}/api/bot/apply_min_formula`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          workspace_id: workspaceId,
          formula:      settings.min_price_formula,
          step_price:   stepPrice,
        }),
      });
      const data = await res.json();
      if (data.status === "success") {
        alert(`✅ ${data.updated_count} محصول آپدیت شد. فراموش نکنید ذخیره کنید!`);
        await loadProducts();
      } else {
        alert("❌ " + (data.message || JSON.stringify(data)));
      }
    } catch {
      alert("خطای ارتباط با سرور");
    }
    setApplyingFormula(false);
  };

  const handlePriceChange = (id: number, field: "min_price" | "max_price", value: string) => {
    setProducts((prev) => prev.map((p) => p.variant_id === id ? { ...p, [field]: value } : p));
  };

  const toggleBot = async () => {
    if (isRunning) {
      await fetch(`${API}/api/bot/stop`, { method: "POST" });
    } else {
      await fetch(`${API}/api/bot/start`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          workspace_id: workspaceId,
          step_price:   parseInt(String(stepPrice)),
          cycle_delay:  parseInt(String(cycleDelay)),
        }),
      });
    }
  };

  const autoDiscover = async (variant_id: number, reference_price: number, current_price: number) => {
    if (!confirm(`کشف خودکار بازه برای تنوع ${variant_id}؟\nحدود ۶۰-۹۰ ثانیه طول می‌کشد.`)) return;
    setDiscoveringId(String(variant_id));
    try {
      const res  = await fetch(`${API}/api/bot/discover_bounds`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          workspace_id:    workspaceId,
          variant_id:      String(variant_id),
          reference_price: parseInt(String(reference_price)) || parseInt(String(current_price)),
          current_price:   parseInt(String(current_price)),
        }),
      });
      const data = await res.json();
      if (data.success) {
        setProducts((prev) =>
          prev.map((p) =>
            String(p.variant_id) === String(variant_id)
              ? { ...p, min_price: data.min_price, max_price: data.max_price, has_config: true }
              : p
          )
        );
        alert(`✅ کف: ${fmtNum(data.min_price)} | سقف: ${fmtNum(data.max_price)}\nفراموش نکنید ذخیره کنید!`);
      } else {
        alert("❌ خطا: " + data.message);
      }
    } catch {
      alert("خطای ارتباط با سرور");
    }
    setDiscoveringId(null);
  };

  // ─── Derived ─────────────────────────────────────────────────────
  const buyboxWinners = products.filter((p) => p.is_buy_box_winner).length;
  const losing        = products.filter((p) => !p.is_buy_box_winner).length;

  const filtered = products.filter((p) => {
    if (filter === "winning")    return p.is_buy_box_winner;
    if (filter === "losing")     return !p.is_buy_box_winner;
    if (filter === "configured") return p.has_config || (p.min_price !== "" && p.max_price !== "");
    return true;
  });

  const uptime = botState.started_at
    ? Math.floor((Date.now() - new Date(botState.started_at).getTime()) / 60000)
    : 0;

  const strategyLabel: Record<string, string> = {
    aggressive:   "تهاجمی",
    conservative: "محافظه‌کار",
    formula:      "فرمول‌محور",
  };

  // ─── Render ───────────────────────────────────────────────────────
  return (
    <div
      className="min-h-screen text-slate-100 p-6"
      dir="rtl"
      style={{
        background: "linear-gradient(135deg, #0a0f1a 0%, #0d1526 50%, #0a0f1a 100%)",
        fontFamily: "'Vazirmatn', 'Tahoma', sans-serif",
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
        .glow-green { box-shadow: 0 0 20px rgba(34,197,94,0.2); }
        .glow-red   { box-shadow: 0 0 20px rgba(239,68,68,0.15); }
        @keyframes scanline { 0%{top:0} 100%{top:100%} }
        .terminal-scanline::before {
          content:''; position:absolute; left:0; right:0; height:1px;
          background:linear-gradient(90deg,transparent,rgba(34,197,94,0.1),transparent);
          animation: scanline 4s linear infinite;
        }
      `}</style>

      <div className="max-w-[1600px] mx-auto space-y-5">

        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div>
            <h1
              className="text-2xl font-bold tracking-tight"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              <span className="text-cyan-400">DK</span>
              <span className="text-slate-300">_Repricer</span>
              <span className="text-slate-600"> v3.0</span>
            </h1>
            <p className="text-slate-500 text-sm mt-0.5">موتور هوشمند رقابت قیمت دیجی‌کالا</p>
          </div>
          <div
            className={`flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-medium ${
              isRunning
                ? "border-green-500/40 text-green-400 bg-green-500/10 glow-green"
                : "border-slate-600 text-slate-400 bg-slate-800/50"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${isRunning ? "bg-green-400 animate-pulse" : "bg-slate-600"}`}
            />
            {isRunning
              ? `در حال رقابت | چرخه #${botState.cycle_count || 0} | ${strategyLabel[settings.strategy_mode] || ""}`
              : "متوقف"}
          </div>
        </div>

        {/* ── Stats Row ── */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <StatCard label="محصولات فعال"  value={fmtNum(products.length)}      sub={`${stats.configured} تنظیم‌شده`} color="cyan" />
          <StatCard label="BuyBox دارم"   value={fmtNum(buyboxWinners)}
            sub={products.length ? `${Math.round(buyboxWinners / products.length * 100)}% نرخ برد` : ""}
            color="green" pulse={isRunning && buyboxWinners > 0}
          />
          <StatCard label="در حال باخت"   value={fmtNum(losing)}               color="red" />
          <StatCard label="آپدیت قیمت"    value={fmtNum(botState.total_updates)} sub="از ابتدای جلسه" color="violet" />
          <StatCard label="برخورد 429"    value={fmtNum(botState.rate_limit_hits || 0)} sub="محدودیت نرخ" color="rose" />
          <StatCard label="آپ‌تایم"        value={isRunning ? `${uptime}m` : "—"}
            sub={botState.step_price ? `step: ${fmtNum(botState.step_price)}` : ""}
            color="amber" pulse={isRunning}
          />
        </div>

        {/* ── Control Panel ── */}
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 backdrop-blur-sm">
          <div className="flex flex-wrap gap-3 items-end">
            {[
              { label: "Workspace ID",        value: workspaceId,  setter: setWorkspaceId,  type: "number", width: "w-28", step: undefined },
              { label: "گام قیمت (تومان)",    value: stepPrice,    setter: setStepPrice,    type: "number", width: "w-32", step: 500 },
              { label: "تاخیر چرخه (ثانیه)", value: cycleDelay,  setter: setCycleDelay,   type: "number", width: "w-32", step: 30 },
            ].map(({ label, value, setter, type, width, step }) => (
              <div key={label} className="flex flex-col gap-1">
                <label className="text-xs text-slate-500">{label}</label>
                <input
                  type={type}
                  value={value}
                  step={step}
                  onChange={(e) => setter(Number(e.target.value) as any)}
                  className={`bg-slate-900 border border-slate-600 text-slate-200 rounded-lg px-3 py-2 text-sm ${width} text-center focus:border-cyan-500 outline-none`}
                />
              </div>
            ))}

            <div className="flex-1" />

            <button
              onClick={() => setShowSettings((v) => !v)}
              className={`border text-sm font-medium px-4 py-2 rounded-lg transition-colors ${
                showSettings
                  ? "bg-cyan-700/30 border-cyan-500/50 text-cyan-300"
                  : "bg-slate-700 border-slate-600 text-slate-300 hover:bg-slate-600"
              }`}
            >
              ⚙️ تنظیمات {showSettings ? "▲" : "▼"}
            </button>
            <button
              onClick={loadProducts}
              disabled={loading}
              className="bg-slate-700 hover:bg-slate-600 text-slate-200 border border-slate-600 px-5 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {loading ? "⏳ دریافت..." : "🔄 دریافت محصولات"}
            </button>
            <button
              onClick={saveConfigs}
              disabled={saving}
              className="bg-emerald-700/80 hover:bg-emerald-600 text-white border border-emerald-600/50 px-5 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {saving ? "⏳" : "💾 ذخیره"}
            </button>
            <button
              onClick={toggleBot}
              className={`px-6 py-2 rounded-lg text-sm font-bold border transition-all ${
                isRunning
                  ? "bg-red-600/80 hover:bg-red-500 border-red-500/50 text-white glow-red"
                  : "bg-cyan-600/80 hover:bg-cyan-500 border-cyan-500/50 text-white"
              }`}
            >
              {isRunning ? "⏹ توقف ربات" : "▶ شروع ربات"}
            </button>
          </div>
        </div>

        {/* ── Settings Panel ── */}
        {showSettings && (
          <SettingsPanel
            settings={settings}
            onChange={setSettings}
            onSave={saveSettings}
            saving={savingSettings}
            onApplyMinFormula={applyMinFormula}
            applyingFormula={applyingFormula}
            workspaceId={workspaceId}
            stepPrice={stepPrice}
          />
        )}

        {/* ── Filter Tabs ── */}
        {products.length > 0 && (
          <div className="flex gap-2">
            {(
              [
                ["all", "همه"],
                ["winning", "برنده BuyBox"],
                ["losing", "در حال باخت"],
                ["configured", "تنظیم‌شده"],
              ] as [string, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`px-4 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                  filter === key
                    ? "bg-cyan-600/30 border-cyan-500/60 text-cyan-300"
                    : "bg-transparent border-slate-700 text-slate-500 hover:text-slate-300"
                }`}
              >
                {label}
              </button>
            ))}
            <span className="text-xs text-slate-600 flex items-center mr-2">
              نمایش {filtered.length} از {products.length}
            </span>
          </div>
        )}

        {/* ── Products Table ── */}
        <div className="bg-slate-800/30 border border-slate-700/40 rounded-xl overflow-hidden backdrop-blur-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-right">
              <thead>
                <tr className="border-b border-slate-700/60 bg-slate-900/40">
                  {["وضعیت", "کد تنوع", "نام محصول", "قیمت فعلی", "قیمت مرجع", "کف مجاز ▼", "سقف مجاز ▲", "عملیات"].map((h) => (
                    <th key={h} className="p-3 text-slate-500 font-medium text-xs">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-16 text-slate-600">
                      {products.length === 0 ? "ابتدا محصولات را دریافت کنید" : "موردی یافت نشد"}
                    </td>
                  </tr>
                )}
                {filtered.map((p) => {
                  const isDiscovering = discoveringId === String(p.variant_id);
                  return (
                    <tr
                      key={p.variant_id}
                      className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors"
                    >
                      <td className="p-3">
                        {p.is_buy_box_winner ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-emerald-900/50 text-emerald-400 border border-emerald-700/40 px-2 py-0.5 rounded-full">
                            🏆 BuyBox
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-red-900/40 text-red-400 border border-red-800/40 px-2 py-0.5 rounded-full">
                            ⚔️ رقابت
                          </span>
                        )}
                      </td>
                      <td className="p-3 font-mono text-xs text-slate-500">{p.variant_id}</td>
                      <td className="p-3 max-w-[200px]">
                        <span className="text-slate-300 truncate block" title={p.title}>{p.title}</span>
                      </td>
                      <td className="p-3 font-bold text-cyan-400 font-mono text-sm">{fmtNum(p.current_price)}</td>
                      <td className="p-3 text-slate-500 font-mono text-xs">{fmtNum(p.reference_price)}</td>
                      <td className="p-3">
                        <input
                          type="number"
                          value={p.min_price}
                          onChange={(e) => handlePriceChange(p.variant_id, "min_price", e.target.value)}
                          placeholder="کف"
                          disabled={isDiscovering}
                          className="bg-slate-900/80 border border-slate-600 hover:border-slate-500 focus:border-cyan-500 text-slate-200 rounded-lg px-2 py-1.5 w-28 text-center text-xs outline-none transition-colors placeholder-slate-600 disabled:opacity-40"
                        />
                      </td>
                      <td className="p-3">
                        <input
                          type="number"
                          value={p.max_price}
                          onChange={(e) => handlePriceChange(p.variant_id, "max_price", e.target.value)}
                          placeholder="سقف"
                          disabled={isDiscovering}
                          className="bg-slate-900/80 border border-slate-600 hover:border-slate-500 focus:border-cyan-500 text-slate-200 rounded-lg px-2 py-1.5 w-28 text-center text-xs outline-none transition-colors placeholder-slate-600 disabled:opacity-40"
                        />
                      </td>
                      <td className="p-3">
                        <button
                          onClick={() => autoDiscover(p.variant_id, p.reference_price, p.current_price)}
                          disabled={isDiscovering || !p.current_price}
                          className="text-xs font-semibold bg-indigo-900/60 hover:bg-indigo-700/60 text-indigo-300 border border-indigo-700/40 hover:border-indigo-500/60 px-3 py-1.5 rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {isDiscovering ? <span className="animate-pulse">⚡ اسکن...</span> : "⚡ کشف خودکار"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Terminal ── */}
        <div className="relative bg-[#050c14] border border-slate-700/40 rounded-xl overflow-hidden terminal-scanline">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/40 bg-slate-900/60">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-red-500/60" />
              <span className="w-3 h-3 rounded-full bg-amber-500/60" />
              <span className="w-3 h-3 rounded-full bg-green-500/60" />
              <span className="text-slate-500 text-xs font-mono mr-2">repricer.log — live feed</span>
              {(botState.rate_limit_hits || 0) > 0 && (
                <span className="text-[10px] bg-rose-900/50 border border-rose-700/40 text-rose-400 px-2 py-0.5 rounded-full">
                  429×{botState.rate_limit_hits}
                </span>
              )}
            </div>
            <button
              onClick={() => fetch(`${API}/api/logs`, { method: "DELETE" }).catch(() => {})}
              className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
            >
              پاک کردن
            </button>
          </div>
          <div ref={logsRef} className="h-56 overflow-y-auto p-4 space-y-1">
            {logs.length === 0 ? (
              <div className="text-slate-700 font-mono text-xs">// در انتظار لاگ...</div>
            ) : (
              logs.map((log, i) => {
                const isSuccess = log.includes("✅");
                const isError   = log.includes("❌") || log.includes("⚠️");
                const is429     = log.includes("429");
                const isAction  = log.includes("⚔️") || log.includes("📈") || log.includes("💰");
                const isBuybox  = log.includes("🏆") || log.includes("BuyBox");
                return (
                  <div
                    key={i}
                    className={`font-mono text-xs leading-5 ${
                      is429      ? "text-rose-400" :
                      isSuccess  ? "text-emerald-400" :
                      isError    ? "text-red-400" :
                      isAction   ? "text-cyan-300" :
                      isBuybox   ? "text-amber-300" :
                      "text-slate-400"
                    }`}
                  >
                    {log}
                  </div>
                );
              })
            )}
          </div>
        </div>

      </div>
    </div>
  );
}