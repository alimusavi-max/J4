"use client";

import { useState, useEffect } from "react";

export default function Dashboard() {
  const [products, setProducts] = useState([]);
  const [logs, setLogs] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const interval = setInterval(() => {
      fetch("http://localhost:8000/api/logs")
        .then((res) => res.json())
        .then((data) => {
          setLogs(data.logs);
          setIsRunning(data.is_running);
        }).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const loadProducts = async () => {
    setLoading(true);
    try {
      const res = await fetch("http://localhost:8000/api/products?workspace_id=1");
      const data = await res.json();
      setProducts(data.variants);
    } catch (err) {
      alert("خطا در ارتباط با سرور بک‌اند");
    }
    setLoading(false);
  };

  const saveConfigs = async () => {
    const configsToSave = {};
    products.forEach((p) => {
      if (p.min_price && p.max_price) {
        configsToSave[p.variant_id] = {
          min_price: parseInt(p.min_price),
          max_price: parseInt(p.max_price),
        };
      }
    });

    await fetch("http://localhost:8000/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ configs: configsToSave }),
    });
    alert("تنظیمات با موفقیت ذخیره شد.");
  };

  const handlePriceChange = (id, field, value) => {
    setProducts(products.map(p => 
      p.variant_id === id ? { ...p, [field]: value } : p
    ));
  };

  const toggleBot = async () => {
    const endpoint = isRunning ? "/api/bot/stop" : "/api/bot/start";
    await fetch(`http://localhost:8000${endpoint}`, { method: "POST" });
  };

  const autoDiscoverBounds = async (variant_id, reference_price, current_price) => {
    if (!confirm("این عملیات با الگوریتم دودویی عمیق، قیمت را ۲۴ بار تست و فوری برمی‌گرداند تا مرز بسیار دقیق کشف شود. حدود ۴۰ ثانیه زمان می‌برد. ادامه؟")) return;
    
    const safeVariantId = String(variant_id);
    const safeCurrentPrice = parseInt(current_price);
    const safeRefPrice = parseInt(reference_price) ? parseInt(reference_price) : safeCurrentPrice;

    alert("الگوریتم اسکن مویرگی شروع شد. لطفاً به ترمینال سیاه‌رنگ پایین صفحه دقت کنید...");
    
    try {
      const res = await fetch("http://localhost:8000/api/bot/discover_bounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
            workspace_id: 1, 
            variant_id: safeVariantId, 
            reference_price: safeRefPrice,
            current_price: safeCurrentPrice
        })
      });
      
      const data = await res.json();
      
      if (data.success) {
          setProducts(products.map(p => 
            String(p.variant_id) === safeVariantId ? { ...p, min_price: data.min_price, max_price: data.max_price } : p
          ));
          alert("✅ بازه با موفقیت استخراج و در جدول جایگذاری شد. یادتان نرود دکمه ذخیره تنظیمات را بزنید!");
      } else {
          alert("❌ خطایی در کشف بازه رخ داد: " + data.message);
      }
    } catch (err) {
      alert("خطا در ارتباط با سرور!");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 p-8 font-sans" dir="rtl">
      <div className="max-w-7xl mx-auto space-y-6">
        
        <div className="bg-white border border-slate-200 p-6 rounded-xl shadow-sm flex justify-between items-center">
          <h1 className="text-2xl font-bold text-slate-800">داشبورد هوشمند قیمت دیجی‌کالا</h1>
          <div className="space-x-4 space-x-reverse">
            <button onClick={loadProducts} disabled={loading} className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
              {loading ? "در حال دریافت..." : "دریافت محصولات"}
            </button>
            <button onClick={saveConfigs} className="bg-emerald-600 text-white px-4 py-2 rounded-lg hover:bg-emerald-700 shadow shadow-emerald-200">
              ذخیره تنظیمات در فایل
            </button>
            <button onClick={toggleBot} className={`px-4 py-2 rounded-lg text-white font-medium shadow ${isRunning ? 'bg-red-500 hover:bg-red-600 shadow-red-200' : 'bg-slate-800 hover:bg-slate-900 shadow-slate-300'}`}>
              {isRunning ? "⏹ توقف ربات" : "▶️ شروع ربات"}
            </button>
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <table className="w-full text-sm text-right">
            <thead className="bg-slate-100 text-slate-700 border-b border-slate-200">
              <tr>
                <th className="p-4 font-semibold">کد تنوع</th>
                <th className="p-4 font-semibold">نام محصول</th>
                <th className="p-4 font-semibold text-blue-800">قیمت فعلی</th>
                <th className="p-4 font-semibold text-slate-500">قیمت مرجع</th>
                <th className="p-4 font-semibold">کف مجاز ما</th>
                <th className="p-4 font-semibold">سقف مجاز ما</th>
                <th className="p-4 font-semibold">عملیات هوشمند</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-800">
              {products.map((product) => (
                <tr key={product.variant_id} className="hover:bg-slate-50 transition-colors">
                  <td className="p-4 font-mono text-slate-500">{product.variant_id}</td>
                  <td className="p-4 truncate max-w-xs" title={product.title}>{product.title}</td>
                  <td className="p-4 font-bold text-blue-600">{product.current_price?.toLocaleString()}</td>
                  <td className="p-4 text-slate-500">{product.reference_price?.toLocaleString() || '-'}</td>
                  <td className="p-4">
                    <input type="number" value={product.min_price} onChange={(e) => handlePriceChange(product.variant_id, 'min_price', e.target.value)}
                      className="border border-slate-300 rounded p-1 w-28 bg-white text-center text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none" placeholder="کف قیمت" />
                  </td>
                  <td className="p-4">
                    <input type="number" value={product.max_price} onChange={(e) => handlePriceChange(product.variant_id, 'max_price', e.target.value)}
                      className="border border-slate-300 rounded p-1 w-28 bg-white text-center text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none" placeholder="سقف قیمت" />
                  </td>
                  <td className="p-4 space-x-2 space-x-reverse flex items-center">
                     {product.is_buy_box_winner ? 
                      <span className="text-emerald-700 bg-emerald-100 px-2 py-1 rounded-full text-[10px] font-bold border border-emerald-200">بای‌باکس</span> : 
                      <span className="text-red-700 bg-red-100 px-2 py-1 rounded-full text-[10px] font-bold border border-red-200">رقیب</span>}
                      
                    <button onClick={() => autoDiscoverBounds(product.variant_id, product.reference_price, product.current_price)} 
                      className="text-xs bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-3 py-1.5 rounded transition-colors font-bold border border-indigo-200 shadow-sm">
                      کشف خودکار ⚡
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-slate-900 rounded-xl shadow-lg p-5 h-64 flex flex-col">
          <h3 className="text-slate-400 mb-3 font-mono text-sm border-b border-slate-700 pb-2">Terminal Logs (Live)</h3>
          <div className="text-emerald-400 font-mono text-sm space-y-1.5 overflow-y-auto flex-1 flex flex-col-reverse">
            {[...logs].reverse().map((log, idx) => (
              <div key={idx} className="opacity-90 hover:opacity-100">{log}</div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}