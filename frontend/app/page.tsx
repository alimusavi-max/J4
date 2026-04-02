"use client";
import { AuthBadge, PriceSparkline,CompetitorCell,ExportImportBar } from "./components";
import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ─── Helpers ────────────────────────────────────────────────────────────────
const fmt = (n: any) =>
  n != null && n !== "" ? Number(n).toLocaleString("fa-IR") : "—";
const fmtNum = (n: any) =>
  n != null && n !== "" ? Number(n).toLocaleString() : "—";

// ─── Types ───────────────────────────────────────────────────────────────────
interface Product {
  variant_id: number;
  product_id?: number;
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
  enabled?: boolean;
}

interface BotState {
  is_running?: boolean;
  workspace_id?: number;
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
  dry_run: boolean;
  variant_cooldown_seconds: number;
  notify_webhook_url: string;
  rate_limit_pause_seconds: number;
  max_consecutive_failures: number;
  my_seller_id: number;
}

const DEFAULT_SETTINGS: Settings = {
  lead_time: 2,
  shipping_type: "seller",
  max_per_order: 4,
  request_delay_min: 3.0,
  request_delay_max: 6.0,
  rate_limit_backoff_base: 15,
  max_retries: 3,
  dry_run: false,
  variant_cooldown_seconds: 300,
  notify_webhook_url: "",
  rate_limit_pause_seconds: 180,
  max_consecutive_failures: 10,
  my_seller_id: 0,
};

type ActiveTab = "dashboard" | "products" | "settings" | "logs";
type FilterMode = "all" | "winning" | "losing" | "enabled" | "disabled";

// ─── localStorage helpers ────────────────────────────────────────────────────
const LS_PRODUCTS_KEY = "dk_repricer_products";
const LS_WORKSPACE_KEY = "dk_repricer_workspace";

function loadFromStorage<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function saveToStorage(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota exceeded — silently ignore
  }
}

// ─── Toast ────────────────────────────────────────────────────────────────────
interface Toast {
  id: number;
  msg: string;
  type: "success" | "error" | "info" | "warn";
}
let toastId = 0;

function ToastContainer({
  toasts,
  remove,
}: {
  toasts: Toast[];
  remove: (id: number) => void;
}) {
  const colors: Record<string, string> = {
    success: "#00ff9d",
    error: "#ff4560",
    warn: "#ffb700",
    info: "#00cfff",
  };
  return (
    <div
      style={{
        position: "fixed",
        bottom: 24,
        right: 24,
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          onClick={() => remove(t.id)}
          style={{
            background: "#0d1117",
            border: `1px solid ${colors[t.type]}55`,
            borderLeft: `3px solid ${colors[t.type]}`,
            color: colors[t.type],
            padding: "10px 16px",
            borderRadius: 4,
            fontSize: 12,
            fontFamily: "'IBM Plex Mono', monospace",
            cursor: "pointer",
            minWidth: 280,
            animation: "slideIn 0.2s ease",
          }}
        >
          {t.type === "success" ? "✓ " : t.type === "error" ? "✗ " : "→ "}
          {t.msg}
        </div>
      ))}
    </div>
  );
}

// ─── Sparkline ────────────────────────────────────────────────────────────────
function Sparkline({
  data,
  color,
  height = 32,
}: {
  data: number[];
  color: string;
  height?: number;
}) {
  if (data.length < 2)
    return <div style={{ height, opacity: 0.2, background: color, borderRadius: 2 }} />;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const w = 80;
  const h = height;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} style={{ overflow: "visible" }}>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <polyline
        points={`0,${h} ${pts} ${w},${h}`}
        fill={`${color}18`}
        stroke="none"
      />
    </svg>
  );
}

// ─── Metric Card ──────────────────────────────────────────────────────────────
function MetricCard({
  label,
  value,
  sub,
  color,
  data,
  pulse,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color: string;
  data?: number[];
  pulse?: boolean;
}) {
  return (
    <div
      style={{
        background: "#0d1117",
        border: "1px solid #1c2333",
        borderTop: `2px solid ${color}`,
        borderRadius: 4,
        padding: "16px 20px",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          bottom: 0,
          right: 0,
          opacity: 0.3,
        }}
      >
        {data && <Sparkline data={data} color={color} />}
      </div>
      <div
        style={{
          fontSize: 10,
          color: "#4a5568",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          fontFamily: "'IBM Plex Mono', monospace",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {pulse && (
          <span
            style={{
              display: "inline-block",
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: color,
              animation: "pulse 1.5s infinite",
            }}
          />
        )}
        {label}
      </div>
      <div
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: color,
          fontFamily: "'IBM Plex Mono', monospace",
          marginTop: 6,
          letterSpacing: "-0.02em",
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            fontSize: 10,
            color: "#4a5568",
            marginTop: 4,
            fontFamily: "'IBM Plex Mono', monospace",
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

// ─── Per-Variant Bot Toggle ──────────────────────────────────────────────────
function VariantBotToggle({
  variant,
  onToggle,
}: {
  variant: Product;
  onToggle: (id: number, enabled: boolean) => void;
}) {
  const enabled = variant.enabled !== false;
  return (
    <button
      onClick={() => onToggle(variant.variant_id, !enabled)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: 3,
        border: `1px solid ${enabled ? "#00ff9d44" : "#ff456044"}`,
        background: enabled ? "#00ff9d11" : "#ff456011",
        color: enabled ? "#00ff9d" : "#ff4560",
        fontSize: 10,
        fontFamily: "'IBM Plex Mono', monospace",
        cursor: "pointer",
        transition: "all 0.15s",
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: enabled ? "#00ff9d" : "#ff4560",
          flexShrink: 0,
          animation: enabled ? "pulse 2s infinite" : "none",
        }}
      />
      {enabled ? "فعال" : "متوقف"}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
export default function RepricerApp() {
  const [tab, setTab] = useState<ActiveTab>("dashboard");

  // ─── FIX: مقداردهی اولیه products از localStorage ──────────────────────────
  const [products, setProducts] = useState<Product[]>(() =>
    loadFromStorage<Product[]>(LS_PRODUCTS_KEY, [])
  );

  const [logs, setLogs] = useState<string[]>([]);
  const [botState, setBotState] = useState<BotState>({});
  const [isRunning, setIsRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);

  // ─── FIX: مقداردهی اولیه workspaceId از localStorage ──────────────────────
  const [cycleDelay, setCycleDelay] = useState(120);
  const [workspaceId, setWorkspaceId] = useState<number>(() =>
    loadFromStorage<number>(LS_WORKSPACE_KEY, 1)
  );

  const [filter, setFilter] = useState<FilterMode>("all");
  const [search, setSearch] = useState("");
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [bulkMin, setBulkMin] = useState("");
  const [bulkMax, setBulkMax] = useState("");
  const [cycleHistory, setCycleHistory] = useState<number[]>([]);
  const [lastSyncTime, setLastSyncTime] = useState<string>(() =>
    loadFromStorage<string>("dk_last_sync", "")
  );
  const logsRef = useRef<HTMLDivElement>(null);

  // ─── FIX: ذخیره products در localStorage هر بار که تغییر می‌کند ───────────
  useEffect(() => {
    if (products.length > 0) {
      saveToStorage(LS_PRODUCTS_KEY, products);
    }
  }, [products]);

  // ─── FIX: ذخیره workspaceId هنگام تغییر ────────────────────────────────────
  useEffect(() => {
    saveToStorage(LS_WORKSPACE_KEY, workspaceId);
  }, [workspaceId]);

  // ─── Toast ─────────────────────────────────────────────────────────────────
  const toast = useCallback((msg: string, type: Toast["type"] = "info") => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);
  const removeToast = useCallback(
    (id: number) => setToasts((t) => t.filter((x) => x.id !== id)),
    []
  );

  // ─── Load Settings ─────────────────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then((r) => r.json())
      .then((d) => {
        if (d.settings) setSettings({ ...DEFAULT_SETTINGS, ...d.settings });
      })
      .catch(() => {});
  }, []);

  // ─── Polling ───────────────────────────────────────────────────────────────
  useEffect(() => {
    const poll = setInterval(() => {
      fetch(`${API}/api/logs?limit=200`)
        .then((r) => r.json())
        .then((d) => {
          setLogs(d.logs || []);
          setIsRunning(!!d.is_running);
          setBotState(d.bot_state || {});
          if (d.bot_state?.cycle_count) {
            setCycleHistory((prev) => [
              ...prev.slice(-19),
              d.bot_state.total_updates || 0,
            ]);
          }
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  // ─── Derived ───────────────────────────────────────────────────────────────
  const buyboxWinners = products.filter((p) => p.is_buy_box_winner).length;
  const enabledVariants = products.filter((p) => p.enabled !== false).length;
  const disabledVariants = products.filter((p) => p.enabled === false).length;
  const uptime = botState.started_at
    ? Math.floor(
        (Date.now() - new Date(botState.started_at).getTime()) / 60000
      )
    : 0;

  const filtered = products
    .filter((p) => {
      if (filter === "winning") return p.is_buy_box_winner;
      if (filter === "losing") return !p.is_buy_box_winner;
      if (filter === "enabled") return p.enabled !== false;
      if (filter === "disabled") return p.enabled === false;
      return true;
    })
    .filter(
      (p) =>
        !search ||
        p.title?.toLowerCase().includes(search.toLowerCase()) ||
        String(p.variant_id).includes(search)
    );

  // ─── Actions ───────────────────────────────────────────────────────────────
  const loadProducts = async () => {
    setLoading(true);
    try {
      const [varRes, cfgRes] = await Promise.all([
        fetch(`${API}/api/products?workspace_id=${workspaceId}`),
        fetch(`${API}/api/config`),
      ]);
      const varData = await varRes.json();
      const cfgData = await cfgRes.json();
      const merged = (varData.variants || []).map((v: Product) => ({
        ...v,
        enabled: cfgData[String(v.variant_id)]?.enabled !== false,
        min_price: cfgData[String(v.variant_id)]?.min_price || v.min_price,
        max_price: cfgData[String(v.variant_id)]?.max_price || v.max_price,
      }));
      setProducts(merged);
      // ─── FIX: ثبت زمان آخرین همگام‌سازی ─────────────────────────────────
      const syncTime = new Date().toLocaleString("fa-IR");
      setLastSyncTime(syncTime);
      saveToStorage("dk_last_sync", syncTime);
      toast(`${varData.total || 0} تنوع دریافت شد`, "success");
    } catch {
      toast("خطا در ارتباط با سرور", "error");
    }
    setLoading(false);
  };

  // ─── FIX: پاک‌کردن کش محصولات ──────────────────────────────────────────────
  const clearProductCache = () => {
    localStorage.removeItem(LS_PRODUCTS_KEY);
    localStorage.removeItem("dk_last_sync");
    setProducts([]);
    setLastSyncTime("");
    toast("کش محصولات پاک شد", "warn");
  };

  const saveConfigs = async () => {
    setSaving(true);
    const configs: Record<string, any> = {};
    products.forEach((p) => {
      if (p.min_price !== "" || p.max_price !== "" || p.has_config) {
        configs[String(p.variant_id)] = {
          ...(p.min_price !== "" && { min_price: parseInt(String(p.min_price)) }),
          ...(p.max_price !== "" && { max_price: parseInt(String(p.max_price)) }),
          enabled: p.enabled !== false,
          strategy: "smart",
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
      toast(`${d.saved_count} تنوع ذخیره شد`, "success");
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
      else toast("خطا: " + (data.detail || "خطای سرور"), "error");
    } catch {
      toast("خطا در ارتباط با سرور", "error");
    }
    setSavingSettings(false);
  };

  const toggleBot = async () => {
    if (isRunning) {
      await fetch(`${API}/api/bot/stop`, { method: "POST" });
      toast("ربات متوقف شد", "warn");
    } else {
      await fetch(`${API}/api/bot/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          cycle_delay: cycleDelay,
        }),
      });
      toast("ربات فعال شد", "success");
    }
  };

  const toggleVariantBot = async (variantId: number, enabled: boolean) => {
    setTogglingId(String(variantId));
    try {
      setProducts((prev) =>
        prev.map((p) =>
          p.variant_id === variantId ? { ...p, enabled } : p
        )
      );
      const res = await fetch(
        `${API}/api/config/${variantId}/toggle?enabled=${enabled}`,
        { method: "PATCH" }
      );
      if (!res.ok) throw new Error("API error");
      toast(
        `تنوع ${variantId} ${enabled ? "فعال" : "متوقف"} شد`,
        enabled ? "success" : "warn"
      );
    } catch {
      setProducts((prev) =>
        prev.map((p) =>
          p.variant_id === variantId ? { ...p, enabled: !enabled } : p
        )
      );
      toast("خطا در تغییر وضعیت", "error");
    }
    setTogglingId(null);
  };

  const bulkToggle = async (enabled: boolean) => {
    if (selectedIds.size === 0) {
      toast("هیچ تنوعی انتخاب نشده", "warn");
      return;
    }
    const ids = Array.from(selectedIds);
    setProducts((prev) =>
      prev.map((p) =>
        selectedIds.has(p.variant_id) ? { ...p, enabled } : p
      )
    );
    await Promise.all(
      ids.map((id) =>
        fetch(`${API}/api/config/${id}/toggle?enabled=${enabled}`, {
          method: "PATCH",
        }).catch(() => {})
      )
    );
    toast(
      `${ids.length} تنوع ${enabled ? "فعال" : "متوقف"} شد`,
      enabled ? "success" : "warn"
    );
    setSelectedIds(new Set());
  };

  const applyBulkPrices = () => {
    if (!bulkMin && !bulkMax) {
      toast("مقداری وارد کنید", "warn");
      return;
    }
    setProducts((prev) =>
      prev.map((p) => {
        if (!selectedIds.has(p.variant_id)) return p;
        return {
          ...p,
          ...(bulkMin ? { min_price: parseInt(bulkMin) } : {}),
          ...(bulkMax ? { max_price: parseInt(bulkMax) } : {}),
        };
      })
    );
    toast(`${selectedIds.size} تنوع آپدیت شد`, "success");
    setBulkMin("");
    setBulkMax("");
  };

  const handlePriceChange = (
    id: number,
    field: "min_price" | "max_price",
    value: string
  ) => {
    setProducts((prev) =>
      prev.map((p) => (p.variant_id === id ? { ...p, [field]: value } : p))
    );
  };

  const selectAll = () => {
    if (selectedIds.size === filtered.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filtered.map((p) => p.variant_id)));
    }
  };

  const copyLogs = () => {
    navigator.clipboard
      .writeText(logs.join("\n"))
      .then(() => toast("لاگ‌ها کپی شد", "success"));
  };

  // ─── Log coloring ──────────────────────────────────────────────────────────
  const logColor = (log: string) => {
    if (log.includes("✅") || log.includes("موفق") || log.includes("👑")) return "#00ff9d";
    if (log.includes("❌") || log.includes("خطا") || log.includes("🛑")) return "#ff4560";
    if (log.includes("⚠️") || log.includes("⏳")) return "#ffb700";
    if (log.includes("429")) return "#ff7700";
    if (log.includes("⚔️") || log.includes("→") || log.includes("🎯") || log.includes("🥊")) return "#00cfff";
    if (log.includes("━━")) return "#2a3447";
    if (log.includes("▶️") || log.includes("⏹") || log.includes("🚀")) return "#a78bfa";
    return "#4a5568";
  };

  // ─── Nav items ─────────────────────────────────────────────────────────────
  const navItems = [
    { id: "dashboard" as ActiveTab, label: "داشبورد", icon: "⬛" },
    { id: "products" as ActiveTab, label: "مدیریت تنوع‌ها", icon: "◈" },
    { id: "settings" as ActiveTab, label: "تنظیمات", icon: "◎" },
    { id: "logs" as ActiveTab, label: "لاگ زنده", icon: "▶" },
  ];

  return (
    <div
      dir="rtl"
      style={{
        display: "flex",
        height: "100vh",
        overflow: "hidden",
        background: "#070c15",
        fontFamily: "'Vazirmatn', 'Tahoma', sans-serif",
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 3px; height: 3px; }
        ::-webkit-scrollbar-track { background: #070c15; }
        ::-webkit-scrollbar-thumb { background: #1c2333; }
        input, select { outline: none; }
        input[type=number]::-webkit-inner-spin-button { opacity: 0; }
        select option { background: #0d1117; color: #e2e8f0; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        @keyframes slideIn { from { transform: translateX(20px); opacity: 0; } to { transform: none; opacity: 1; } }
      `}</style>

      <ToastContainer toasts={toasts} remove={removeToast} />

      {/* ─── Sidebar ─────────────────────────────────────────────────────────── */}
      <aside
        style={{
          width: 220,
          background: "#0d1117",
          borderLeft: "1px solid #1c2333",
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
        }}
      >
        {/* Logo */}
        <div
          style={{
            padding: "24px 20px 16px",
            borderBottom: "1px solid #1c2333",
          }}
        >
          <div
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 15,
              fontWeight: 600,
              letterSpacing: "0.05em",
            }}
          >
            <span style={{ color: "#ff4560" }}>DK</span>
            <span style={{ color: "#1c2333" }}>::</span>
            <span style={{ color: "#00ff9d" }}>bot</span>
          </div>
          <div
            style={{
              fontSize: 9,
              color: "#2a3447",
              fontFamily: "'IBM Plex Mono', monospace",
              marginTop: 3,
              letterSpacing: "0.1em",
            }}
          >
            SMART REPRICER
          </div>
        </div>

        {/* Bot status pill */}
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #1c2333" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              background: isRunning ? "#00ff9d08" : "#0d1117",
              border: `1px solid ${isRunning ? "#00ff9d22" : "#1c2333"}`,
              borderRadius: 3,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: isRunning ? "#00ff9d" : "#1c2333",
                flexShrink: 0,
                animation: isRunning ? "pulse 1.5s infinite" : "none",
              }}
            />
            <div>
              <div
                style={{
                  fontSize: 10,
                  color: isRunning ? "#00ff9d" : "#2a3447",
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
              >
                {isRunning ? "هوش مصنوعی فعال" : "سیستم متوقف"}
              </div>
              {isRunning && (
                <div
                  style={{
                    fontSize: 9,
                    color: "#4a5568",
                    fontFamily: "'IBM Plex Mono', monospace",
                    marginTop: 2,
                  }}
                >
                  چرخه #{botState.cycle_count || 0} | {uptime}m
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: "8px 0" }}>
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 20px",
                background: tab === item.id ? "#131b2e" : "transparent",
                border: "none",
                borderRight: `2px solid ${tab === item.id ? "#00cfff" : "transparent"}`,
                color: tab === item.id ? "#00cfff" : "#4a5568",
                fontSize: 13,
                cursor: "pointer",
                textAlign: "right",
                transition: "all 0.15s",
                fontFamily: "'Vazirmatn', sans-serif",
              }}
            >
              <span
                style={{
                  fontFamily: "'IBM Plex Mono', monospace",
                  fontSize: 14,
                  color: tab === item.id ? "#00cfff" : "#2a3447",
                }}
              >
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
        </nav>

        {/* Workspace + Controls */}
        <div
          style={{
            padding: "16px",
            borderTop: "1px solid #1c2333",
          }}
        >
          <div
            style={{
              fontSize: 9,
              color: "#2a3447",
              fontFamily: "'IBM Plex Mono', monospace",
              marginBottom: 6,
            }}
          >
            WORKSPACE
          </div>
          <input
            type="number"
            value={workspaceId}
            min={1}
            onChange={(e) => setWorkspaceId(Number(e.target.value))}
            style={{
              width: "100%",
              background: "#070c15",
              border: "1px solid #1c2333",
              color: "#4a5568",
              borderRadius: 3,
              padding: "6px 10px",
              fontSize: 12,
              fontFamily: "'IBM Plex Mono', monospace",
              marginBottom: 10,
            }}
          />

          <div
            style={{
              fontSize: 9,
              color: "#2a3447",
              fontFamily: "'IBM Plex Mono', monospace",
              marginBottom: 6,
            }}
          >
            DELAY (ثانیه)
          </div>
          <input
            type="number"
            value={cycleDelay}
            min={30}
            step={30}
            disabled={isRunning}
            onChange={(e) => setCycleDelay(Number(e.target.value))}
            style={{
              width: "100%",
              background: "#070c15",
              border: "1px solid #1c2333",
              color: "#4a5568",
              borderRadius: 3,
              padding: "6px 10px",
              fontSize: 12,
              fontFamily: "'IBM Plex Mono', monospace",
              marginBottom: 12,
              opacity: isRunning ? 0.4 : 1,
            }}
          />

          <button
            onClick={toggleBot}
            style={{
              width: "100%",
              padding: "10px",
              borderRadius: 3,
              border: `1px solid ${isRunning ? "#ff456044" : "#00ff9d44"}`,
              background: isRunning ? "#ff456011" : "#00ff9d11",
              color: isRunning ? "#ff4560" : "#00ff9d",
              fontSize: 12,
              fontWeight: 700,
              fontFamily: "'IBM Plex Mono', monospace",
              cursor: "pointer",
              letterSpacing: "0.05em",
            }}
          >
            {isRunning ? "■ STOP" : "▶ START AI"}
          </button>
        </div>
      </aside>

      {/* ─── Main ───────────────────────────────────────────────────────────── */}
      <main
        style={{
          flex: 1,
          overflow: "auto",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Top bar */}
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 28px",
            borderBottom: "1px solid #1c2333",
            background: "#0d1117",
            flexShrink: 0,
          }}
        >
          <div>
            <h1
              style={{
                fontSize: 15,
                fontWeight: 600,
                color: "#e2e8f0",
                letterSpacing: "0.02em",
              }}
            >
              {navItems.find((n) => n.id === tab)?.label}
            </h1>
            <div
              style={{
                fontSize: 10,
                color: "#2a3447",
                fontFamily: "'IBM Plex Mono', monospace",
                marginTop: 3,
              }}
            >
              {tab === "products" &&
                `${products.length} تنوع | ${enabledVariants} فعال | ${disabledVariants} متوقف`}
              {tab === "dashboard" &&
                `workspace: ${workspaceId} | ${isRunning ? "در حال اجرا" : "متوقف"}${lastSyncTime ? ` | آخرین همگام‌سازی: ${lastSyncTime}` : ""}`}
              {tab === "settings" && "پیکربندی هوش مصنوعی"}
              {tab === "logs" && `${logs.length} خط لاگ`}
            </div>
          </div>
          {settings.dry_run && (
            <div
              style={{
                padding: "4px 10px",
                background: "#ffb70011",
                border: "1px solid #ffb70044",
                borderRadius: 3,
                color: "#ffb700",
                fontSize: 10,
                fontFamily: "'IBM Plex Mono', monospace",
                letterSpacing: "0.1em",
              }}
            >
              ◈ DRY RUN MODE
            </div>
          )}
        </header>

        <div style={{ flex: 1, overflow: "auto", padding: 28 }}>
          {/* ═══ DASHBOARD ══════════════════════════════════════════════════════ */}
          {tab === "dashboard" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              {/* Metrics */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                  gap: 12,
                }}
              >
                <MetricCard
                  label="کل تنوع‌ها"
                  value={products.length}
                  sub={`${enabledVariants} فعال در ربات`}
                  color="#00cfff"
                  data={[products.length]}
                />
                <MetricCard
                  label="بای‌باکس"
                  value={buyboxWinners}
                  sub={
                    products.length > 0
                      ? `${Math.round((buyboxWinners / products.length) * 100)}% نرخ برد`
                      : "—"
                  }
                  color="#00ff9d"
                  pulse={isRunning}
                  data={cycleHistory}
                />
                <MetricCard
                  label="تغییرات قیمت"
                  value={botState.total_updates || 0}
                  sub="توسط هوش مصنوعی"
                  color="#a78bfa"
                  pulse={isRunning}
                  data={cycleHistory}
                />
                <MetricCard
                  label="چرخه‌ها"
                  value={botState.cycle_count || 0}
                  sub={isRunning ? `${uptime} دقیقه آپ‌تایم` : "متوقف"}
                  color={isRunning ? "#00ff9d" : "#2a3447"}
                  pulse={isRunning}
                />
              </div>

              {/* Quick actions */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 12,
                }}
              >
                <div
                  style={{
                    background: "#0d1117",
                    border: "1px solid #1c2333",
                    borderRadius: 4,
                    padding: 20,
                  }}
                >
                  <div
                    style={{
                      fontSize: 10,
                      color: "#4a5568",
                      fontFamily: "'IBM Plex Mono', monospace",
                      letterSpacing: "0.1em",
                      marginBottom: 16,
                    }}
                  >
                    دسترسی سریع
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <button
                      onClick={loadProducts}
                      disabled={loading}
                      style={{
                        padding: "10px 16px",
                        background: "#00cfff11",
                        border: "1px solid #00cfff33",
                        borderRadius: 3,
                        color: "#00cfff",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "'IBM Plex Mono', monospace",
                        textAlign: "right",
                      }}
                    >
                      {loading ? "در حال دریافت..." : "↓ همگام‌سازی محصولات با سایت"}
                    </button>
                    <button
                      onClick={() => setTab("products")}
                      style={{
                        padding: "10px 16px",
                        background: "#a78bfa11",
                        border: "1px solid #a78bfa33",
                        borderRadius: 3,
                        color: "#a78bfa",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "'IBM Plex Mono', monospace",
                        textAlign: "right",
                      }}
                    >
                      ◈ ویرایش کف و سقف قیمت‌ها
                    </button>
                    <button
                      onClick={() => setTab("logs")}
                      style={{
                        padding: "10px 16px",
                        background: "#00ff9d11",
                        border: "1px solid #00ff9d33",
                        borderRadius: 3,
                        color: "#00ff9d",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "'IBM Plex Mono', monospace",
                        textAlign: "right",
                      }}
                    >
                      ▶ رصد تصمیم‌گیری‌های ربات
                    </button>
                    {/* ─── FIX: دکمه پاک‌کردن کش ────────────────────────────── */}
                    <button
                      onClick={clearProductCache}
                      style={{
                        padding: "10px 16px",
                        background: "#ff456011",
                        border: "1px solid #ff456033",
                        borderRadius: 3,
                        color: "#ff4560",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "'IBM Plex Mono', monospace",
                        textAlign: "right",
                      }}
                    >
                      ⊗ پاک‌کردن کش محصولات
                    </button>
                  </div>
                </div>

                {/* Mini log */}
                <div
                  style={{
                    background: "#070c15",
                    border: "1px solid #1c2333",
                    borderRadius: 4,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      padding: "12px 16px",
                      borderBottom: "1px solid #1c2333",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <span
                      style={{ width: 6, height: 6, borderRadius: "50%", background: "#ff4560" }}
                    />
                    <span
                      style={{ width: 6, height: 6, borderRadius: "50%", background: "#ffb700" }}
                    />
                    <span
                      style={{ width: 6, height: 6, borderRadius: "50%", background: "#00ff9d" }}
                    />
                    <span
                      style={{
                        fontSize: 9,
                        color: "#2a3447",
                        fontFamily: "'IBM Plex Mono', monospace",
                        marginRight: 8,
                      }}
                    >
                      LIVE LOG
                    </span>
                  </div>
                  <div
                    style={{
                      height: 180,
                      overflow: "hidden",
                      padding: "8px 16px",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "flex-end",
                    }}
                  >
                    {logs.slice(-8).map((log, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: 10,
                          color: logColor(log),
                          fontFamily: "'IBM Plex Mono', monospace",
                          lineHeight: 1.8,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {log}
                      </div>
                    ))}
                    {logs.length === 0 && (
                      <div
                        style={{
                          fontSize: 10,
                          color: "#1c2333",
                          fontFamily: "'IBM Plex Mono', monospace",
                        }}
                      >
                        // در انتظار لاگ...
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ═══ PRODUCTS ═══════════════════════════════════════════════════════ */}
          {tab === "products" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {/* Toolbar */}
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 8,
                  alignItems: "center",
                  background: "#0d1117",
                  border: "1px solid #1c2333",
                  borderRadius: 4,
                  padding: "12px 16px",
                }}
              >
                {/* Search */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    background: "#070c15",
                    border: "1px solid #1c2333",
                    borderRadius: 3,
                    padding: "6px 12px",
                    flex: 1,
                    minWidth: 180,
                  }}
                >
                  <span style={{ fontSize: 10, color: "#2a3447" }}>⌕</span>
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="جستجو در تنوع‌ها..."
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "#e2e8f0",
                      fontSize: 12,
                      flex: 1,
                    }}
                  />
                </div>

                {/* Filters */}
                {(
                  [
                    ["all", "همه"],
                    ["enabled", "فعال"],
                    ["disabled", "متوقف"],
                    ["winning", "برنده"],
                    ["losing", "بازنده"],
                  ] as [FilterMode, string][]
                ).map(([k, l]) => (
                  <button
                    key={k}
                    onClick={() => setFilter(k)}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 3,
                      border: `1px solid ${filter === k ? "#00cfff44" : "#1c2333"}`,
                      background: filter === k ? "#00cfff11" : "transparent",
                      color: filter === k ? "#00cfff" : "#4a5568",
                      fontSize: 11,
                      cursor: "pointer",
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    {l}
                  </button>
                ))}

                <div style={{ flex: 1 }} />

                {/* ─── FIX: نمایش زمان آخرین همگام‌سازی ──────────────────── */}
                {lastSyncTime && (
                  <span style={{
                    fontSize: 9,
                    color: "#2a3447",
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}>
                    آخرین sync: {lastSyncTime}
                  </span>
                )}

                <button
                  onClick={loadProducts}
                  disabled={loading}
                  style={{
                    padding: "7px 14px",
                    borderRadius: 3,
                    border: "1px solid #00cfff44",
                    background: "#00cfff11",
                    color: "#00cfff",
                    fontSize: 11,
                    cursor: "pointer",
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}
                >
                  {loading ? "..." : "↓ دریافت از سایت"}
                </button>
                <button
                  onClick={saveConfigs}
                  disabled={saving}
                  style={{
                    padding: "7px 14px",
                    borderRadius: 3,
                    border: "1px solid #00ff9d44",
                    background: "#00ff9d11",
                    color: "#00ff9d",
                    fontSize: 11,
                    cursor: "pointer",
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}
                >
                  {saving ? "..." : "↑ ذخیره تغییرات"}
                </button>
              </div>

              {/* Bulk actions */}
              {selectedIds.size > 0 && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 16px",
                    background: "#00cfff08",
                    border: "1px solid #00cfff22",
                    borderRadius: 4,
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      fontSize: 11,
                      color: "#00cfff",
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    {selectedIds.size} کالا انتخاب‌شده
                  </span>

                  <button
                    onClick={() => bulkToggle(true)}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 3,
                      border: "1px solid #00ff9d44",
                      background: "#00ff9d11",
                      color: "#00ff9d",
                      fontSize: 11,
                      cursor: "pointer",
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    ▶ فعال‌سازی همه
                  </button>
                  <button
                    onClick={() => bulkToggle(false)}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 3,
                      border: "1px solid #ff456044",
                      background: "#ff456011",
                      color: "#ff4560",
                      fontSize: 11,
                      cursor: "pointer",
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    ■ توقف همه
                  </button>

                  <div style={{ width: 1, height: 20, background: "#1c2333" }} />

                  <input
                    type="number"
                    value={bulkMin}
                    onChange={(e) => setBulkMin(e.target.value)}
                    placeholder="کف قیمت"
                    style={{
                      width: 110,
                      padding: "5px 8px",
                      background: "#070c15",
                      border: "1px solid #1c2333",
                      borderRadius: 3,
                      color: "#e2e8f0",
                      fontSize: 11,
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  />
                  <input
                    type="number"
                    value={bulkMax}
                    onChange={(e) => setBulkMax(e.target.value)}
                    placeholder="سقف قیمت"
                    style={{
                      width: 110,
                      padding: "5px 8px",
                      background: "#070c15",
                      border: "1px solid #1c2333",
                      borderRadius: 3,
                      color: "#e2e8f0",
                      fontSize: 11,
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  />
                  <button
                    onClick={applyBulkPrices}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 3,
                      border: "1px solid #a78bfa44",
                      background: "#a78bfa11",
                      color: "#a78bfa",
                      fontSize: 11,
                      cursor: "pointer",
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    اعمال دسته‌جمعی
                  </button>
                  <button
                    onClick={() => setSelectedIds(new Set())}
                    style={{
                      padding: "5px 10px",
                      borderRadius: 3,
                      border: "1px solid #1c2333",
                      background: "transparent",
                      color: "#4a5568",
                      fontSize: 11,
                      cursor: "pointer",
                    }}
                  >
                    ✕
                  </button>
                </div>
              )}

              {/* Table */}
              <div
                style={{
                  background: "#0d1117",
                  border: "1px solid #1c2333",
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <div style={{ overflowX: "auto" }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: 12,
                    }}
                  >
                    <thead>
                      <tr
                        style={{
                          background: "#070c15",
                          borderBottom: "1px solid #1c2333",
                        }}
                      >
                        <th style={thStyle}>
                          <input
                            type="checkbox"
                            checked={
                              selectedIds.size === filtered.length &&
                              filtered.length > 0
                            }
                            onChange={selectAll}
                          />
                        </th>
                        <th style={thStyle}>کنترل ربات</th>
                        <th style={thStyle}>بای‌باکس</th>
                        <th style={thStyle}>DKPC</th>
                        <th style={{ ...thStyle, textAlign: "right", minWidth: 200 }}>
                          نام کالا
                        </th>
                        <th style={thStyle}>قیمت شما</th>
                        <th style={thStyle}>کف قیمت (مجاز)</th>
                        <th style={thStyle}>سقف قیمت (مجاز)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.length === 0 ? (
                        <tr>
                          <td
                            colSpan={8}
                            style={{
                              textAlign: "center",
                              padding: 48,
                              color: "#1c2333",
                              fontFamily: "'IBM Plex Mono', monospace",
                              fontSize: 12,
                            }}
                          >
                            {products.length === 0
                              ? "// دکمه دریافت را بزنید"
                              : "// موردی یافت نشد"}
                          </td>
                        </tr>
                      ) : (
                        filtered.map((p) => {
                          const enabled = p.enabled !== false;
                          const isToggling = togglingId === String(p.variant_id);

                          return (
                            <tr
                              key={p.variant_id}
                              style={{
                                borderBottom: "1px solid #0d1117",
                                opacity: enabled ? 1 : 0.45,
                                background: enabled
                                  ? "transparent"
                                  : "#ff456005",
                                transition: "opacity 0.2s",
                              }}
                            >
                              <td style={tdStyle}>
                                <input
                                  type="checkbox"
                                  checked={selectedIds.has(p.variant_id)}
                                  onChange={() =>
                                    setSelectedIds((prev) => {
                                      const s = new Set(prev);
                                      s.has(p.variant_id)
                                        ? s.delete(p.variant_id)
                                        : s.add(p.variant_id);
                                      return s;
                                    })
                                  }
                                />
                              </td>

                              <td style={tdStyle}>
                                <div
                                  style={{
                                    opacity: isToggling ? 0.5 : 1,
                                    pointerEvents: isToggling ? "none" : "auto",
                                    display: "flex",
                                    justifyContent: "center"
                                  }}
                                >
                                  <VariantBotToggle
                                    variant={p}
                                    onToggle={toggleVariantBot}
                                  />
                                </div>
                              </td>

                              <td style={tdStyle}>
                                {p.is_buy_box_winner ? (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      color: "#00ff9d",
                                      fontFamily: "'IBM Plex Mono', monospace",
                                    }}
                                  >
                                    ◆ برنده
                                  </span>
                                ) : (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      color: "#ff4560",
                                      fontFamily: "'IBM Plex Mono', monospace",
                                    }}
                                  >
                                    ◇ بازنده
                                  </span>
                                )}
                              </td>

                              <td style={tdStyle}>
                                <span
                                  style={{
                                    fontFamily: "'IBM Plex Mono', monospace",
                                    fontSize: 11,
                                    color: "#2a3447",
                                  }}
                                >
                                  {p.variant_id}
                                </span>
                              </td>

                              <td
                                style={{
                                  ...tdStyle,
                                  textAlign: "right",
                                  maxWidth: 200,
                                }}
                              >
                                <span
                                  style={{
                                    display: "block",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                    color: "#94a3b8",
                                    fontSize: 12,
                                  }}
                                  title={p.title}
                                >
                                  {p.title}
                                </span>
                              </td>

                              <td style={tdStyle}>
                                <span
                                  style={{
                                    fontFamily: "'IBM Plex Mono', monospace",
                                    color: "#00cfff",
                                    fontWeight: 600,
                                    fontSize: 12,
                                  }}
                                >
                                  {fmtNum(p.current_price)}
                                </span>
                              </td>

                              <td style={tdStyle}>
                                <input
                                  type="number"
                                  value={p.min_price}
                                  onChange={(e) =>
                                    handlePriceChange(
                                      p.variant_id,
                                      "min_price",
                                      e.target.value
                                    )
                                  }
                                  placeholder="تعیین نشده"
                                  style={{
                                    width: 100,
                                    padding: "4px 8px",
                                    background: "#070c15",
                                    border: "1px solid #1c2333",
                                    borderRadius: 3,
                                    color: p.min_price ? "#00ff9d" : "#2a3447",
                                    fontSize: 11,
                                    fontFamily: "'IBM Plex Mono', monospace",
                                  }}
                                />
                              </td>

                              <td style={tdStyle}>
                                <input
                                  type="number"
                                  value={p.max_price}
                                  onChange={(e) =>
                                    handlePriceChange(
                                      p.variant_id,
                                      "max_price",
                                      e.target.value
                                    )
                                  }
                                  placeholder="تعیین نشده"
                                  style={{
                                    width: 100,
                                    padding: "4px 8px",
                                    background: "#070c15",
                                    border: "1px solid #1c2333",
                                    borderRadius: 3,
                                    color: p.max_price ? "#ff4560" : "#2a3447",
                                    fontSize: 11,
                                    fontFamily: "'IBM Plex Mono', monospace",
                                  }}
                                />
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
                <div
                  style={{
                    padding: "8px 16px",
                    borderTop: "1px solid #070c15",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      color: "#2a3447",
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    {filtered.length} / {products.length} تنوع
                  </span>
                  {selectedIds.size > 0 && (
                    <span
                      style={{
                        fontSize: 10,
                        color: "#00cfff",
                        fontFamily: "'IBM Plex Mono', monospace",
                      }}
                    >
                      {selectedIds.size} کالا انتخاب‌شده
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ═══ SETTINGS ═══════════════════════════════════════════════════════ */}
          {tab === "settings" && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 16,
                maxWidth: 700,
              }}
            >
              <Section title="پیکربندی هوش مصنوعی">
                <div
                  style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
                >
                  {[
                    { k: "variant_cooldown_seconds", l: "تأخیر بین بررسی مجدد هر کالا (ثانیه)", step: 60 },
                    { k: "my_seller_id", l: "شناسه فروشگاه شما", step: 1 },
                    { k: "rate_limit_pause_seconds", l: "مکث امنیتی دیجی‌کالا (ثانیه)", step: 30 },
                    { k: "max_retries", l: "تعداد تلاش در صورت قطعی", step: 1 },
                    { k: "lead_time", l: "مدت آماده‌سازی (روز)", step: 1 },
                    { k: "max_per_order", l: "حداکثر سفارش هر کاربر", step: 1 },
                  ].map((f) => (
                    <SettingInput
                      key={f.k}
                      label={f.l}
                      value={(settings as any)[f.k]}
                      step={f.step}
                      onChange={(v) =>
                        setSettings((prev) => ({ ...prev, [f.k]: v }))
                      }
                    />
                  ))}
                </div>
              </Section>

              <Section title="تنظیمات متفرقه">
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "#4a5568",
                        fontFamily: "'IBM Plex Mono', monospace",
                        marginBottom: 6,
                        letterSpacing: "0.05em",
                      }}
                    >
                      نوع ارسال به مشتری
                    </div>
                    <select
                      value={settings.shipping_type}
                      onChange={(e) =>
                        setSettings((prev) => ({ ...prev, shipping_type: e.target.value }))
                      }
                      style={selectStyle}
                    >
                      <option value="seller">توسط فروشنده</option>
                      <option value="digikala">انبار دیجی‌کالا</option>
                    </select>
                  </div>

                  <label
                    style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", marginTop: 12 }}
                  >
                    <div
                      onClick={() =>
                        setSettings((prev) => ({ ...prev, dry_run: !prev.dry_run }))
                      }
                      style={{
                        width: 40,
                        height: 22,
                        background: settings.dry_run ? "#ffb70033" : "#1c2333",
                        border: `1px solid ${settings.dry_run ? "#ffb700" : "#2a3447"}`,
                        borderRadius: 11,
                        position: "relative",
                        cursor: "pointer",
                        transition: "all 0.2s",
                      }}
                    >
                      <div
                        style={{
                          position: "absolute",
                          top: 2,
                          left: settings.dry_run ? 20 : 2,
                          width: 16,
                          height: 16,
                          borderRadius: "50%",
                          background: settings.dry_run ? "#ffb700" : "#2a3447",
                          transition: "left 0.2s",
                        }}
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: 13, color: "#94a3b8" }}>
                        حالت شبیه‌سازی (Dry Run)
                      </div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "#4a5568",
                          fontFamily: "'IBM Plex Mono', monospace",
                        }}
                      >
                        در این حالت ربات لاگ می‌اندازد اما قیمتی به سایت ارسال نمی‌کند
                      </div>
                    </div>
                  </label>
                </div>
              </Section>

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  onClick={saveSettings}
                  disabled={savingSettings}
                  style={{
                    padding: "10px 24px",
                    background: "#00ff9d11",
                    border: "1px solid #00ff9d44",
                    borderRadius: 3,
                    color: "#00ff9d",
                    fontSize: 13,
                    fontWeight: 700,
                    cursor: "pointer",
                    fontFamily: "'IBM Plex Mono', monospace",
                    letterSpacing: "0.05em",
                  }}
                >
                  {savingSettings ? "..." : "↑ ذخیره تنظیمات"}
                </button>
              </div>
            </div>
          )}

          {/* ═══ LOGS ════════════════════════════════════════════════════════════ */}
          {tab === "logs" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span
                  style={{
                    fontSize: 10,
                    color: "#4a5568",
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}
                >
                  {logs.length} خط عملیات
                </span>
                <div style={{ flex: 1 }} />
                <button
                  onClick={copyLogs}
                  style={{
                    padding: "5px 12px",
                    background: "transparent",
                    border: "1px solid #1c2333",
                    borderRadius: 3,
                    color: "#4a5568",
                    fontSize: 11,
                    cursor: "pointer",
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}
                >
                  ⊕ کپی
                </button>
                <button
                  onClick={() =>
                    fetch(`${API}/api/logs`, { method: "DELETE" }).then(() =>
                      setLogs([])
                    )
                  }
                  style={{
                    padding: "5px 12px",
                    background: "#ff456011",
                    border: "1px solid #ff456033",
                    borderRadius: 3,
                    color: "#ff4560",
                    fontSize: 11,
                    cursor: "pointer",
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}
                >
                  ⊗ پاکسازی
                </button>
              </div>

              <div
                style={{
                  background: "#070c15",
                  border: "1px solid #1c2333",
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "10px 16px",
                    borderBottom: "1px solid #1c2333",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    background: "#0d1117",
                  }}
                >
                  <span
                    style={{ width: 8, height: 8, borderRadius: "50%", background: "#ff4560" }}
                  />
                  <span
                    style={{ width: 8, height: 8, borderRadius: "50%", background: "#ffb700" }}
                  />
                  <span
                    style={{ width: 8, height: 8, borderRadius: "50%", background: "#00ff9d" }}
                  />
                  <span
                    style={{
                      fontFamily: "'IBM Plex Mono', monospace",
                      fontSize: 10,
                      color: "#2a3447",
                      marginRight: 12,
                    }}
                  >
                    AI.Core::ExecutionLog — workspace {workspaceId}
                  </span>
                  {isRunning && (
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: "#00ff9d",
                        animation: "pulse 1.5s infinite",
                        marginRight: 4,
                      }}
                    />
                  )}
                </div>

                <div
                  ref={logsRef}
                  style={{
                    height: "calc(100vh - 280px)",
                    overflowY: "auto",
                    padding: "16px 20px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                  }}
                >
                  {logs.length === 0 ? (
                    <span
                      style={{
                        color: "#1c2333",
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: 12,
                      }}
                    >
                      $ در انتظار دریافت لاگ از سرور...
                    </span>
                  ) : (
                    logs.map((log, i) => (
                      <div
                        key={i}
                        style={{
                          color: logColor(log),
                          fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 11,
                          lineHeight: 1.8,
                          borderBottom: log.includes("━━")
                            ? "1px solid #1c2333"
                            : "none",
                          paddingBottom: log.includes("━━") ? 4 : 0,
                          marginBottom: log.includes("━━") ? 4 : 0,
                        }}
                      >
                        {log}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// ─── Small helpers ────────────────────────────────────────────────────────────
const thStyle: React.CSSProperties = {
  padding: "10px 12px",
  textAlign: "center",
  fontSize: 10,
  fontFamily: "'IBM Plex Mono', monospace",
  color: "#2a3447",
  letterSpacing: "0.08em",
  fontWeight: 600,
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "10px 12px",
  textAlign: "center",
  verticalAlign: "middle",
  borderBottom: "1px solid #0d1117",
};

const inputStyle: React.CSSProperties = {
  padding: "6px 10px",
  background: "#070c15",
  border: "1px solid #1c2333",
  borderRadius: 3,
  color: "#e2e8f0",
  fontSize: 12,
  fontFamily: "'IBM Plex Mono', monospace",
};

const selectStyle: React.CSSProperties = {
  padding: "6px 10px",
  background: "#070c15",
  border: "1px solid #1c2333",
  borderRadius: 3,
  color: "#e2e8f0",
  fontSize: 12,
  fontFamily: "'IBM Plex Mono', monospace",
  cursor: "pointer",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "#0d1117",
        border: "1px solid #1c2333",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid #1c2333",
          fontSize: 10,
          fontFamily: "'IBM Plex Mono', monospace",
          color: "#4a5568",
          letterSpacing: "0.1em",
          background: "#070c15",
        }}
      >
        {title.toUpperCase()}
      </div>
      <div style={{ padding: 16 }}>{children}</div>
    </div>
  );
}

function SettingInput({
  label,
  value,
  step,
  onChange,
}: {
  label: string;
  value: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          color: "#4a5568",
          fontFamily: "'IBM Plex Mono', monospace",
          marginBottom: 6,
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </div>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ ...inputStyle, width: "100%" }}
      />
    </div>
  );
}