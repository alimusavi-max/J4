"use client";
/**
 * frontend/app/components.tsx
 *
 * کامپوننت‌های جدید — این فایل را در frontend/app/ بساز
 * و در page.tsx import کن
 *
 * import { AuthBadge, PriceSparkline, CompetitorCell, ExportImportBar } from "./components";
 */

import { useState, useEffect, useCallback } from "react";

const API = "http://localhost:8000";

// ─── Auth Badge ───────────────────────────────────────────────────────────────
/**
 * نمایش وضعیت کوکی در header
 * هر ۶۰ ثانیه یه بار چک می‌کند
 */
export function AuthBadge({ workspaceId }: { workspaceId: number }) {
  const [status, setStatus] = useState<{
    cookie_valid: boolean;
    age_hours: number;
    status: string;
  } | null>(null);

  const check = useCallback(() => {
    fetch(`${API}/api/auth/status?workspace_id=${workspaceId}`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => {});
  }, [workspaceId]);

  useEffect(() => {
    check();
    const t = setInterval(check, 60_000);
    return () => clearInterval(t);
  }, [check]);

  if (!status) return null;

  const ok       = status.cookie_valid;
  const ageH     = status.age_hours;
  const expiring = ok && ageH > 20; // کوکی بیش از ۲۰ ساعت داره — احتمال expire

  const color = !ok ? "#ff4560" : expiring ? "#ffb700" : "#00ff9d";
  const label = !ok
    ? "کوکی منقضی"
    : expiring
    ? `کوکی رو به انقضا (${ageH.toFixed(0)}h)`
    : `کوکی معتبر (${ageH.toFixed(0)}h)`;

  return (
    <div
      title={`وضعیت: ${status.status}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        background: `${color}11`,
        border: `1px solid ${color}44`,
        borderRadius: 3,
        fontSize: 10,
        fontFamily: "'IBM Plex Mono', monospace",
        color,
        cursor: "default",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          animation: expiring ? "pulse 1s infinite" : "none",
          flexShrink: 0,
        }}
      />
      {label}
    </div>
  );
}


// ─── Price Sparkline (mini chart) ─────────────────────────────────────────────
/**
 * نمودار کوچک تغییرات قیمت برای هر ردیف جدول
 */
interface PricePoint {
  price: number;
  is_winner: boolean;
  at: string;
}

export function PriceSparkline({
  data,
  width = 70,
  height = 24,
}: {
  data: PricePoint[];
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) {
    return (
      <div
        style={{
          width,
          height,
          background: "#1c2333",
          borderRadius: 2,
          opacity: 0.3,
        }}
      />
    );
  }

  const prices  = data.map((d) => d.price);
  const maxP    = Math.max(...prices);
  const minP    = Math.min(...prices);
  const range   = maxP - minP || 1;

  const pts = data
    .map((d, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((d.price - minP) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const last     = data[data.length - 1];
  const color    = last.is_winner ? "#00ff9d" : "#ff4560";
  const lastX    = width;
  const lastY    = height - ((last.price - minP) / range) * height;

  return (
    <svg
      width={width}
      height={height}
      style={{ overflow: "visible", display: "block" }}
    >
      {/* منطقه زیر نمودار */}
      <polyline
        points={`0,${height} ${pts} ${width},${height}`}
        fill={`${color}15`}
        stroke="none"
      />
      {/* خط نمودار */}
      <polyline
        points={pts}
        fill="none"
        stroke={`${color}88`}
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      {/* نقطه آخر */}
      <circle cx={lastX} cy={lastY} r="2.5" fill={color} />
    </svg>
  );
}


// ─── Competitor Cell ──────────────────────────────────────────────────────────
/**
 * نمایش قیمت رقیب و فاصله با قیمت خودمان در جدول
 */
export function CompetitorCell({
  myPrice,
  buyBoxPrice,
  isWinner,
}: {
  myPrice: number;
  buyBoxPrice?: number;
  isWinner: boolean;
}) {
  if (!buyBoxPrice || buyBoxPrice <= 0) {
    return (
      <span
        style={{
          fontSize: 10,
          color: "#2a3447",
          fontFamily: "'IBM Plex Mono', monospace",
        }}
      >
        —
      </span>
    );
  }

  const diff     = buyBoxPrice - myPrice;
  const diffPct  = ((diff / buyBoxPrice) * 100).toFixed(1);
  const isAbove  = diff > 0;    // بای‌باکس از ما گران‌تره
  const isEqual  = diff === 0;

  const color = isWinner
    ? "#00ff9d"
    : isAbove
    ? "#ffb700"   // بای‌باکس گران‌تر — فرصت داریم
    : "#ff4560";  // بای‌باکس ارزون‌تر — باید پایین بیایم

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <span
        style={{
          fontSize: 11,
          fontFamily: "'IBM Plex Mono', monospace",
          color: "#94a3b8",
        }}
      >
        {buyBoxPrice.toLocaleString()}
      </span>
      {!isEqual && (
        <span
          style={{
            fontSize: 9,
            fontFamily: "'IBM Plex Mono', monospace",
            color,
          }}
        >
          {isAbove ? "+" : ""}{diff.toLocaleString()} ({isAbove ? "+" : ""}{diffPct}%)
        </span>
      )}
    </div>
  );
}


// ─── Export / Import Bar ──────────────────────────────────────────────────────
/**
 * نوار export/import config — برای قرار دادن در settings tab
 */
export function ExportImportBar({
  onImported,
}: {
  onImported: () => void;
}) {
  const [importing, setImporting] = useState(false);
  const [msg, setMsg]             = useState("");

  const handleExport = async () => {
    try {
      const res  = await fetch(`${API}/api/config/export`);
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `dk_repricer_backup_${new Date().toISOString().slice(0,10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg("✓ فایل backup دانلود شد");
    } catch {
      setMsg("✗ خطا در export");
    }
    setTimeout(() => setMsg(""), 3000);
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const res  = await fetch(`${API}/api/config/import`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          configs:  data.configs  || {},
          settings: data.settings || null,
        }),
      });
      const d = await res.json();
      setMsg(`✓ ${d.configs_count} تنوع وارد شد`);
      onImported();
    } catch {
      setMsg("✗ فایل نامعتبر است");
    }
    setImporting(false);
    e.target.value = "";
    setTimeout(() => setMsg(""), 3000);
  };

  return (
    <div
      style={{
        display:     "flex",
        alignItems:  "center",
        gap:         10,
        padding:     "12px 16px",
        background:  "#070c15",
        border:      "1px solid #1c2333",
        borderRadius: 4,
      }}
    >
      <span
        style={{
          fontSize: 10,
          color:    "#4a5568",
          fontFamily: "'IBM Plex Mono', monospace",
          flex: 1,
        }}
      >
        BACKUP / RESTORE
      </span>

      {msg && (
        <span
          style={{
            fontSize: 10,
            color: msg.startsWith("✓") ? "#00ff9d" : "#ff4560",
            fontFamily: "'IBM Plex Mono', monospace",
          }}
        >
          {msg}
        </span>
      )}

      <button
        onClick={handleExport}
        style={{
          padding:    "6px 14px",
          background: "#00cfff11",
          border:     "1px solid #00cfff33",
          borderRadius: 3,
          color:      "#00cfff",
          fontSize:   11,
          cursor:     "pointer",
          fontFamily: "'IBM Plex Mono', monospace",
        }}
      >
        ↓ خروجی backup
      </button>

      <label
        style={{
          padding:    "6px 14px",
          background: "#a78bfa11",
          border:     "1px solid #a78bfa33",
          borderRadius: 3,
          color:      importing ? "#4a5568" : "#a78bfa",
          fontSize:   11,
          cursor:     importing ? "not-allowed" : "pointer",
          fontFamily: "'IBM Plex Mono', monospace",
        }}
      >
        {importing ? "..." : "↑ بازیابی از فایل"}
        <input
          type="file"
          accept=".json"
          onChange={handleImport}
          style={{ display: "none" }}
          disabled={importing}
        />
      </label>
    </div>
  );
}


// ─── Learning Memory Stats ────────────────────────────────────────────────────
/**
 * نمایش آمار یادگیری ربات از learning_memory.json
 */
interface MemoryStats {
  seller_id: string;
  win_rate:  number;
  best_gap:  number;
  obs_count: number;
}

export function LearningMemoryWidget({ workspaceId }: { workspaceId: number }) {
  const [stats, setStats] = useState<MemoryStats[]>([]);

  useEffect(() => {
    // از endpoint metrics اطلاعات memory رو بگیر
    fetch(`${API}/api/metrics?workspace_id=${workspaceId}`)
      .then((r) => r.json())
      .then((d) => {
        // parse کردن cache_monitor_history و stats
        const raw = d.metrics?.stats || {};
        setStats([]); // فعلاً خالی — نیاز به endpoint اختصاصی داره
      })
      .catch(() => {});
  }, [workspaceId]);

  if (stats.length === 0) return null;

  return (
    <div
      style={{
        background:  "#0d1117",
        border:      "1px solid #1c2333",
        borderRadius: 4,
        overflow:    "hidden",
      }}
    >
      <div
        style={{
          padding:     "10px 16px",
          borderBottom:"1px solid #1c2333",
          fontSize:    10,
          fontFamily:  "'IBM Plex Mono', monospace",
          color:       "#4a5568",
          background:  "#070c15",
        }}
      >
        LEARNING MEMORY
      </div>
      <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 6 }}>
        {stats.map((s) => (
          <div
            key={s.seller_id}
            style={{
              display:        "flex",
              justifyContent: "space-between",
              fontSize:       11,
              fontFamily:     "'IBM Plex Mono', monospace",
              color:          "#4a5568",
            }}
          >
            <span>Seller {s.seller_id}</span>
            <span style={{ color: s.win_rate > 0.7 ? "#00ff9d" : "#ffb700" }}>
              win: {(s.win_rate * 100).toFixed(0)}%
            </span>
            <span>gap: {s.best_gap.toLocaleString()}</span>
            <span>{s.obs_count} obs</span>
          </div>
        ))}
      </div>
    </div>
  );
}