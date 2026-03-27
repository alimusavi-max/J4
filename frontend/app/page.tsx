"use client";

import { useState, useEffect, useRef } from "react";

const API = "http://localhost:8000";

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmt = (n) => n ? Number(n).toLocaleString("fa-IR") : "—";
const fmtNum = (n) => n ? Number(n).toLocaleString() : "—";

function StatCard({ label, value, sub, color = "cyan", pulse = false }) {
  const colors = {
    cyan:   "from-cyan-500/20 to-cyan-600/5 border-cyan-500/30 text-cyan-300",
    green:  "from-green-500/20 to-green-600/5 border-green-500/30 text-green-300",
    amber:  "from-amber-500/20 to-amber-600/5 border-amber-500/30 text-amber-300",
    red:    "from-red-500/20 to-red-600/5 border-red-500/30 text-red-300",
    violet: "from-violet-500/20 to-violet-600/5 border-violet-500/30 text-violet-300",
  };
  return (
    <div className={`relative bg-gradient-to-br ${colors[color]} border rounded-xl p-4 overflow-hidden`}>
      {pulse && <span className="absolute top-3 right-3 flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span><span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span></span>}
      <div className="text-2xl font-bold font-mono tracking-tight">{value}</div>
      <div className="text-xs text-slate-400 mt-1">{label}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [products, setProducts] = useState([]);
  const [logs, setLogs] = useState([]);
  const [botState, setBotState] = useState({});
  const [isRunning, setIsRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [stepPrice, setStepPrice] = useState(1000);
  const [cycleDelay, setCycleDelay] = useState(120);
  const [workspaceId, setWorkspaceId] = useState(1);
  const [filter, setFilter] = useState("all"); // all | winning | losing | configured
  const [discoveringId, setDiscoveringId] = useState(null);
  const [stats, setStats] = useState({ total: 0, configured: 0 });
  const logsRef = useRef(null);

  // ─── Polling ──────────────────────────────────────────────────────
  useEffect(() => {
    const poll = setInterval(() => {
      fetch(`${API}/api/logs?limit=150`)
        .then(r => r.json())
        .then(d => {
          setLogs(d.logs || []);
          setIsRunning(d.is_running);
          setBotState(d.bot_state || {});
        }).catch(() => {});
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  // ─── Load Products ─────────────────────────────────────────────────
  const loadProducts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/products?workspace_id=${workspaceId}`);
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
    const configs = {};
    products.forEach(p => {
      if (p.min_price !== '' && p.max_price !== '') {
        configs[String(p.variant_id)] = {
          min_price: parseInt(p.min_price),
          max_price: parseInt(p.max_price),
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
      alert(`✅ ${d.saved_count} محصول ذخیره شد.`);
    } catch {
      alert("خطا در ذخیره‌سازی");
    }
    setSaving(false);
  };

  const handlePriceChange = (id, field, value) => {
    setProducts(prev => prev.map(p => p.variant_id === id ? { ...p, [field]: value } : p));
  };

  const toggleBot = async () => {
    if (isRunning) {
      await fetch(`${API}/api/bot/stop`, { method: "POST" });
    } else {
      await fetch(`${API}/api/bot/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          step_price: parseInt(stepPrice),
          cycle_delay: parseInt(cycleDelay),
        }),
      });
    }
  };

  const autoDiscover = async (variant_id, reference_price, current_price) => {
    if (!confirm(`کشف خودکار بازه برای تنوع ${variant_id}؟\nحدود ۶۰-۹۰ ثانیه طول می‌کشد.`)) return;
    setDiscoveringId(String(variant_id));

    try {
      const res = await fetch(`${API}/api/bot/discover_bounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          variant_id: String(variant_id),
          reference_price: parseInt(reference_price) || parseInt(current_price),
          current_price: parseInt(current_price),
        }),
      });
      const data = await res.json();
      if (data.success) {
        setProducts(prev => prev.map(p =>
          String(p.variant_id) === String(variant_id)
            ? { ...p, min_price: data.min_price, max_price: data.max_price, has_config: true }
            : p
        ));
        alert(`✅ کف: ${fmtNum(data.min_price)} | سقف: ${fmtNum(data.max_price)}\nفراموش نکنید ذخیره کنید!`);
      } else {
        alert("❌ خطا: " + data.message);
      }
    } catch {
      alert("خطای ارتباط با سرور");
    }
    setDiscoveringId(null);
  };

  // ─── Derived ───────────────────────────────────────────────────────
  const buyboxWinners = products.filter(p => p.is_buy_box_winner).length;
  const losing = products.filter(p => !p.is_buy_box_winner).length;
  const configured = products.filter(p => p.has_config || (p.min_price && p.max_price)).length;

  const filtered = products.filter(p => {
    if (filter === "winning") return p.is_buy_box_winner;
    if (filter === "losing") return !p.is_buy_box_winner;
    if (filter === "configured") return p.has_config || (p.min_price && p.max_price);
    return true;
  });

  const uptime = botState.started_at
    ? Math.floor((Date.now() - new Date(botState.started_at)) / 60000)
    : 0;

  return (
    <div
      className="min-h-screen text-slate-100 p-6"
      dir="rtl"
      style={{
        background: "linear-gradient(135deg, #0a0f1a 0%, #0d1526 50%, #0a0f1a 100%)",
        fontFamily: "'Vazirmatn', 'Tahoma', sans-serif",
      }}
    >
      {/* Google Font */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
        .glow-green { box-shadow: 0 0 20px rgba(34,197,94,0.2); }
        .glow-red { box-shadow: 0 0 20px rgba(239,68,68,0.15); }
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
            <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              <span className="text-cyan-400">DK</span>
              <span className="text-slate-300">_Repricer</span>
              <span className="text-slate-600"> v2.0</span>
            </h1>
            <p className="text-slate-500 text-sm mt-0.5">موتور هوشمند رقابت قیمت دیجی‌کالا</p>
          </div>
          <div className={`flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-medium ${isRunning ? 'border-green-500/40 text-green-400 bg-green-500/10 glow-green' : 'border-slate-600 text-slate-400 bg-slate-800/50'}`}>
            <span className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-400 animate-pulse' : 'bg-slate-600'}`}></span>
            {isRunning ? `در حال رقابت — چرخه #${botState.cycle_count || 0}` : 'متوقف'}
          </div>
        </div>

        {/* ── Stats Row ── */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="محصولات فعال" value={fmtNum(products.length)} sub={`${configured} تنظیم‌شده`} color="cyan" />
          <StatCard label="BuyBox دارم" value={fmtNum(buyboxWinners)} sub={products.length ? `${Math.round(buyboxWinners/products.length*100)}% نرخ برد` : ''} color="green" pulse={isRunning && buyboxWinners > 0} />
          <StatCard label="در حال باخت" value={fmtNum(losing)} color="red" />
          <StatCard label="آپدیت قیمت" value={fmtNum(botState.total_updates)} sub="از ابتدای جلسه" color="violet" />
          <StatCard label="آپ‌تایم" value={isRunning ? `${uptime}m` : '—'} sub={botState.step_price ? `step: ${fmtNum(botState.step_price)}` : ''} color="amber" pulse={isRunning} />
        </div>

        {/* ── Control Panel ── */}
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 backdrop-blur-sm">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Workspace ID</label>
              <input type="number" value={workspaceId} onChange={e => setWorkspaceId(e.target.value)}
                className="bg-slate-900 border border-slate-600 text-slate-200 rounded-lg px-3 py-2 text-sm w-28 text-center focus:border-cyan-500 outline-none" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">گام قیمت (تومان)</label>
              <input type="number" value={stepPrice} onChange={e => setStepPrice(e.target.value)} step="500"
                className="bg-slate-900 border border-slate-600 text-slate-200 rounded-lg px-3 py-2 text-sm w-32 text-center focus:border-cyan-500 outline-none" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">تاخیر چرخه (ثانیه)</label>
              <input type="number" value={cycleDelay} onChange={e => setCycleDelay(e.target.value)} step="30"
                className="bg-slate-900 border border-slate-600 text-slate-200 rounded-lg px-3 py-2 text-sm w-32 text-center focus:border-cyan-500 outline-none" />
            </div>

            <div className="flex-1" />

            <button onClick={loadProducts} disabled={loading}
              className="bg-slate-700 hover:bg-slate-600 text-slate-200 border border-slate-600 px-5 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
              {loading ? "⏳ دریافت..." : "🔄 دریافت محصولات"}
            </button>
            <button onClick={saveConfigs} disabled={saving}
              className="bg-emerald-700/80 hover:bg-emerald-600 text-white border border-emerald-600/50 px-5 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
              {saving ? "⏳" : "💾 ذخیره تنظیمات"}
            </button>
            <button onClick={toggleBot}
              className={`px-6 py-2 rounded-lg text-sm font-bold border transition-all ${isRunning ? 'bg-red-600/80 hover:bg-red-500 border-red-500/50 text-white glow-red' : 'bg-cyan-600/80 hover:bg-cyan-500 border-cyan-500/50 text-white'}`}>
              {isRunning ? "⏹ توقف ربات" : "▶ شروع ربات"}
            </button>
          </div>
        </div>

        {/* ── Filter Tabs ── */}
        {products.length > 0 && (
          <div className="flex gap-2">
            {[["all","همه"], ["winning","برنده BuyBox"], ["losing","در حال باخت"], ["configured","تنظیم‌شده"]].map(([key, label]) => (
              <button key={key} onClick={() => setFilter(key)}
                className={`px-4 py-1.5 rounded-full text-xs font-medium border transition-colors ${filter === key ? 'bg-cyan-600/30 border-cyan-500/60 text-cyan-300' : 'bg-transparent border-slate-700 text-slate-500 hover:text-slate-300'}`}>
                {label}
              </button>
            ))}
          </div>
        )}

        {/* ── Products Table ── */}
        <div className="bg-slate-800/30 border border-slate-700/40 rounded-xl overflow-hidden backdrop-blur-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-right">
              <thead>
                <tr className="border-b border-slate-700/60 bg-slate-900/40">
                  <th className="p-3 text-slate-500 font-medium text-xs">وضعیت</th>
                  <th className="p-3 text-slate-500 font-medium text-xs">کد تنوع</th>
                  <th className="p-3 text-slate-500 font-medium text-xs">نام محصول</th>
                  <th className="p-3 text-slate-400 font-medium text-xs">قیمت فعلی</th>
                  <th className="p-3 text-slate-500 font-medium text-xs">قیمت مرجع</th>
                  <th className="p-3 text-slate-500 font-medium text-xs">کف مجاز ▼</th>
                  <th className="p-3 text-slate-500 font-medium text-xs">سقف مجاز ▲</th>
                  <th className="p-3 text-slate-500 font-medium text-xs">عملیات</th>
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
                  const hasConfig = p.min_price !== '' && p.max_price !== '';
                  const isDiscovering = discoveringId === String(p.variant_id);

                  return (
                    <tr key={p.variant_id}
                      className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                      <td className="p-3">
                        {p.is_buy_box_winner
                          ? <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-emerald-900/50 text-emerald-400 border border-emerald-700/40 px-2 py-0.5 rounded-full">🏆 BuyBox</span>
                          : <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-red-900/40 text-red-400 border border-red-800/40 px-2 py-0.5 rounded-full">⚔️ رقابت</span>}
                      </td>
                      <td className="p-3 font-mono text-xs text-slate-500">{p.variant_id}</td>
                      <td className="p-3 max-w-[200px]">
                        <span className="text-slate-300 truncate block" title={p.title}>{p.title}</span>
                      </td>
                      <td className="p-3 font-bold text-cyan-400 font-mono text-sm">{fmtNum(p.current_price)}</td>
                      <td className="p-3 text-slate-500 font-mono text-xs">{fmtNum(p.reference_price)}</td>
                      <td className="p-3">
                        <input type="number" value={p.min_price}
                          onChange={e => handlePriceChange(p.variant_id, 'min_price', e.target.value)}
                          placeholder="کف" disabled={isDiscovering}
                          className="bg-slate-900/80 border border-slate-600 hover:border-slate-500 focus:border-cyan-500 text-slate-200 rounded-lg px-2 py-1.5 w-28 text-center text-xs outline-none transition-colors placeholder-slate-600 disabled:opacity-40"
                        />
                      </td>
                      <td className="p-3">
                        <input type="number" value={p.max_price}
                          onChange={e => handlePriceChange(p.variant_id, 'max_price', e.target.value)}
                          placeholder="سقف" disabled={isDiscovering}
                          className="bg-slate-900/80 border border-slate-600 hover:border-slate-500 focus:border-cyan-500 text-slate-200 rounded-lg px-2 py-1.5 w-28 text-center text-xs outline-none transition-colors placeholder-slate-600 disabled:opacity-40"
                        />
                      </td>
                      <td className="p-3">
                        <button
                          onClick={() => autoDiscover(p.variant_id, p.reference_price, p.current_price)}
                          disabled={isDiscovering || !p.current_price}
                          className="text-xs font-semibold bg-indigo-900/60 hover:bg-indigo-700/60 text-indigo-300 border border-indigo-700/40 hover:border-indigo-500/60 px-3 py-1.5 rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed">
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
              <span className="w-3 h-3 rounded-full bg-red-500/60"></span>
              <span className="w-3 h-3 rounded-full bg-amber-500/60"></span>
              <span className="w-3 h-3 rounded-full bg-green-500/60"></span>
              <span className="text-slate-500 text-xs font-mono mr-2">repricer.log — live feed</span>
            </div>
            <button onClick={() => fetch(`${API}/api/logs`, { method: "DELETE" }).catch(() => {})}
              className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors">پاک کردن</button>
          </div>
          <div ref={logsRef} className="h-56 overflow-y-auto p-4 space-y-1">
            {logs.length === 0
              ? <div className="text-slate-700 font-mono text-xs">// در انتظار لاگ...</div>
              : logs.map((log, i) => {
                  const isSuccess = log.includes('✅');
                  const isError = log.includes('❌') || log.includes('⚠️');
                  const isAction = log.includes('⚔️') || log.includes('📈') || log.includes('💰');
                  const isBuybox = log.includes('🏆') || log.includes('BuyBox');
                  return (
                    <div key={i} className={`font-mono text-xs leading-5 ${isSuccess ? 'text-emerald-400' : isError ? 'text-red-400' : isAction ? 'text-cyan-300' : isBuybox ? 'text-amber-300' : 'text-slate-400'}`}>
                      {log}
                    </div>
                  );
                })}
          </div>
        </div>

      </div>
    </div>
  );
}