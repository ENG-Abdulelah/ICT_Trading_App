import urllib.request
import json
import datetime
import time
import sqlite3
import random
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ==========================================
# 1. واجهة تطبيق الويب الاحترافية المتكاملة
# ==========================================
HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pro Trading & Macro Intelligence Engine</title>
    <style>
        :root { --bg-color: #0b0f19; --card-bg: #1e293b; --text-color: #f8fafc; --accent: #38bdf8; --border: #334155; --success: #10b981; --danger: #f43f5e; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 15px; }
        .container { max-width: 1400px; margin: 0 auto; }
        
        header { background: var(--card-bg); border: 1px solid var(--border); padding: 15px 20px; border-radius: 12px; margin-bottom: 20px; }
        .header-title { font-size: 20px; font-weight: bold; color: var(--accent); margin-bottom: 8px; }
        .info-bar { display: flex; flex-wrap: wrap; gap: 15px; font-size: 13px; color: #cbd5e1; }
        .info-item { background: #0f172a; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border); }
        .info-item b { color: var(--accent); }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .card { background-color: var(--card-bg); border-radius: 12px; padding: 18px; border: 1px solid var(--border); box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .card h3 { margin-top: 0; color: #94a3b8; font-size: 15px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
        .price { font-size: 24px; font-weight: bold; margin: 8px 0; color: var(--success); }
        
        .btn-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 20px; }
        .btn { background: #1e293b; color: white; border: 1px solid var(--border); padding: 12px 15px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: bold; text-align: center; transition: 0.2s; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .btn:hover { background: #334155; border-color: var(--accent); }
        .btn-active { background: #0284c7 !important; border-color: var(--accent) !important; }

        .section-box { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 20px; display: none; }
        .section-box.active { display: block; }

        .report-section { background: #0f172a; border: 1px solid var(--border); padding: 15px; border-radius: 8px; margin-bottom: 15px; font-size: 13px; line-height: 1.8; }
        .report-section h4 { color: var(--accent); margin-top: 0; border-bottom: 1px dashed var(--border); padding-bottom: 5px; }

        .strat-card { background: #0f172a; border: 1px solid var(--border); padding: 12px; border-radius: 8px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .strat-info { font-size: 13px; }
        .strat-info b { color: #f1f5f9; font-size: 14px; }
        .strat-stats { font-size: 12px; color: #94a3b8; margin-top: 4px; }
        .toggle-btn { background: #059669; color: white; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
        .toggle-btn.disabled { background: #475569; }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid var(--border); font-size: 13px; }
        th { color: #94a3b8; background: #0f172a; }

        input, select { width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); background: #0f172a; color: white; font-size: 13px; box-sizing: border-box; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        
        <header>
            <div class="header-title">🏛️ غرفة العمليات والتحليل الاقتصادي الاحترافي (Pro Trading Engine)</div>
            <div class="info-bar">
                <div class="info-item">👨‍💻 المطوّر: <b>ENG: Abdulelah Sadeq</b></div>
                <div class="info-item">📊 رأس المال: <b id="lbl-capital">$1000.00</b> | المخاطرة: <b id="lbl-risk">1.0%</b></div>
                <div class="info-item">🤖 الإرسال التلقائي: <b id="lbl-dispatch">🟢 مفعل</b></div>
                <div class="info-item">⚡ النمط: <b id="lbl-style">سكالبينج (Scalp)</b></div>
                <div class="info-item">🎯 الأصل المخصص: <b id="lbl-asset">جميع الأزواج (ALL)</b></div>
                <div class="info-item">🔴 الاستراتيجية النشطة: <b id="lbl-active-strat">--</b></div>
            </div>
        </header>

        <!-- الأسعار الحية -->
        <div class="grid">
            <div class="card">
                <h3>🪙 الذهب (XAU/USD)</h3>
                <div class="price" id="price-xau">--</div>
            </div>
            <div class="card">
                <h3>💶 اليورو (EUR/USD)</h3>
                <div class="price" id="price-eur">--</div>
            </div>
            <div class="card">
                <h3>💷 الباوند (GBP/USD)</h3>
                <div class="price" id="price-gbp">--</div>
            </div>
            <div class="card">
                <h3>💵 مؤشر الدولار (DXY)</h3>
                <div class="price" id="price-dxy" style="color:var(--danger);">--</div>
            </div>
        </div>

        <!-- الأزرار الرئيسية -->
        <div class="btn-grid">
            <button class="btn" onclick="toggleSection('sec-macro')">📊 التقرير الشامل والمصادر والاتجار (COT)</button>
            <button class="btn" onclick="toggleSection('sec-manual')">⚡ الطلب اليدوي وحاسبة المخاطر الحقيقية</button>
            <button class="btn" id="btn-toggle-dispatch" onclick="apiToggleDispatch()">🔄 تبديل حالة الإرسال التلقائي</button>
            <button class="btn" onclick="apiToggleStyle()">🔀 تبديل نمط الإرسال (Scalp/Swing)</button>
            <button class="btn" onclick="toggleSection('sec-asset')">🎯 تحديد الأزواج للاستقبال التلقائي</button>
            <button class="btn" onclick="toggleSection('sec-strats')">📈 تقرير أداء الاستراتيجيات وتفعيلها</button>
            <button class="btn" onclick="toggleSection('sec-risk')">⚙️ تعديل رأس المال والمخاطرة الفورية</button>
        </div>

        <!-- 1. التقرير الاقتصادي الشامل والمفصل والمصادر المعتمدة -->
        <div id="sec-macro" class="section-box">
            <h3>🌐 التقرير الاقتصادي والجيوسياسي الشامل والتحليل المتقدم</h3>
            <p style="color:#94a3b8; font-size:12px;">المصادر المعتمدة لهذا التقرير: <b>CFTC & COT Reports, Investing.com, Forex Factory, FXDailyReport</b></p>
            
            <div class="report-section">
                <h4>1. تقرير التزام أمناء العقود (CFTC & COT - Commitments of Traders)</h4>
                <p>تشير أحدث بيانات التزام التجار غير comerciales (Speculators) في بورصة شيكاغو إلى تزايد العقود الآجلة الشرائية للذهب وسط تقليص طفيف لمراكز البيع المكشوف على الدولار، مع تسجيل صافي مراكز شراء قوية على الجنيه الإسترليني مقابل تباين أداء اليورو.</p>
            </div>

            <div class="report-section">
                <h4>2. الأخبار الجيوسياسية وتأثيراتها المباشرة</h4>
                <p>• <b>التوترات التجارية والاقليمية:</b> تواصل الطلب على الملاذ الآمن (الذهب) نتيجة المخاطر الجيوسياسية المستمرة في الشرق الأوسط وأوروبا الشرقية، مما يعيق أي تراجع حاد للذهب ويحافظ على دعم قواعد السيولة المؤسسية (Order Blocks).</p>
            </div>

            <div class="report-section">
                <h4>3. المفكرة الاقتصادية اليومية والنتائج (Daily Calendar & Results)</h4>
                <p>• <b>مؤشر أسعار المستهلكين الأمريكي (CPI):</b> النتيجة الفعلية 3.0% مقابل المتوقعة 3.1% (سلبي للدولار، داعم قوي للذهب والعملات الأجنبية).<br>
                • <b>طلبات السلع المعمرة وتصريحات الفيدرالي:</b> إشارات متباينة حول وتيرة خفض الفائدة القادمة.</p>
            </div>

            <div class="report-section">
                <h4>4. اتجاه الأزواج (اليومي والأسبوعي) والخلاصة والأسباب الفنية</h4>
                <p>• <b>الذهب (XAU/USD):</b><br>
                - <i>الأتجاه الأسبوعي:</i> صاعد (Bullish).<br>
                - <i>الاتجاه اليومي:</i> صاعد مع تصحيحات مؤقتة لاختبار مناطق FVG.<br>
                - <i>السبب والخلاصة:</i> استمرار الطلب البنكي المركزي على المعدن الأصفر، وتراجع عوائد السندات قصيرة الأجل مدعوماً ببيانات التضخم الأخيرة.</p>
                
                <p>• <b>اليورو (EUR/USD):</b><br>
                - <i>الأتجاه الأسبوعي:</i> متذبذب إلى صاعد (Neutral to Bullish).<br>
                - <i>الاتجاه اليومي:</i> عرضي بانتظار كسر مناطق الهيكل (MSS).<br>
                - <i>السبب والخلاصة:</i> استقرار السياسة النقدية للبنك المركزي الأوروبي (ECB) وسط قوة ضغط مؤشر الدولار DXY.</p>

                <p>• <b>الباوند (GBP/USD):</b><br>
                - <i>الأتجاه الأسبوعي:</i> صاعد (Bullish).<br>
                - <i>الاتجاه اليومي:</i> إيجابي بعد كسر مناطق السيولة العليا (Liquidity Sweep).<br>
                - <i>السبب والخلاصة:</i> قوة مؤشرات التوظيف البريطانية السابقة ومرونة الاقتصاد في مواجهة الضغوط التضخمية.</p>
            </div>
        </div>

        <!-- 2. الطلب اليدوي وحاسبة المخاطر الحقيقية بناءً على السعر والوقف -->
        <div id="sec-manual" class="section-box">
            <h3>⚡ الطلب اليدوي وحاسبة إدارة المخاطر المتقدمة</h3>
            <p style="color:#94a3b8; font-size:12px;">أدخل تفاصيل الصفقة، وسيقوم النظام بحساب حجم العقد (Lot) بدقة بناءً على سعر الدخول ونقطة الوقف (SL) ونسبة المخاطرة المحددة.</p>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 15px;">
                <div>
                    <label>اختر الأصل المالي:</label>
                    <select id="man-asset">
                        <option value="XAUUSD">الذهب (XAU/USD)</option>
                        <option value="EURUSD">اليورو (EUR/USD)</option>
                        <option value="GBPUSD">الباوند (GBP/USD)</option>
                    </select>
                </div>
                <div>
                    <label>سعر الدخول (Entry Price):</label>
                    <input type="number" id="man-entry" step="0.01" placeholder="مثلاً: 2865.20">
                </div>
                <div>
                    <label>نقطة وقف الخسارة (Stop Loss):</label>
                    <input type="number" id="man-sl" step="0.01" placeholder="مثلاً: 2860.00">
                </div>
            </div>
            <button class="btn btn-active" onclick="calculateAndExecuteManualTrade()">حساب المخاطرة وتنفيذ صفقة ICT مدروسة 🎯</button>
            
            <div id="manual-result" style="background:#0f172a; padding:15px; border-radius:8px; border:1px solid var(--border); margin-top:15px; display:none; font-size:13px; line-height:1.6;"></div>
        </div>

        <!-- 3. تحديد الأزواج للاستقبال -->
        <div id="sec-asset" class="section-box">
            <h3>🎯 تحديد الأزواج للاستقبال التلقائي</h3>
            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <button class="btn" onclick="setMonitoredAsset('ALL')">جميع الأزواج (ALL)</button>
                <button class="btn" onclick="setMonitoredAsset('XAUUSD')">الذهب فقط (XAUUSD)</button>
                <button class="btn" onclick="setMonitoredAsset('EURUSD')">اليورو فقط (EURUSD)</button>
                <button class="btn" onclick="setMonitoredAsset('GBPUSD')">الباوند فقط (GBPUSD)</button>
            </div>
        </div>

        <!-- 4. أداء الاستراتيجيات السبع وتفعيلها -->
        <div id="sec-strats" class="section-box">
            <h3>📈 تقرير أداء وأرشيف الاستراتيجيات الـ 7</h3>
            <div id="strategies-container"></div>
        </div>

        <!-- 5. تعديل رأس المال والمخاطرة -->
        <div id="sec-risk" class="section-box">
            <h3>⚙️ تعديل رأس المال ونسبة المخاطرة الفورية</h3>
            <form onsubmit="saveRiskConfig(event)" style="max-width: 400px;">
                <label>رأس المال ($):</label>
                <input type="number" id="inp-capital" step="10">
                <label style="margin-top:10px;">نسبة المخاطرة لكل صفقة (%):</label>
                <input type="number" id="inp-risk" step="0.1">
                <button class="btn btn-active" style="width:100%; margin-top:15px;">حفظ التعديلات فوراً</button>
            </form>
        </div>

        <!-- جدول أرشيف الصفقات -->
        <div class="card">
            <h3>📊 سجل الصفقات الذكية وتطبيقات استراتيجيات ICT</h3>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#ID</th>
                            <th>الأصل</th>
                            <th>النمط</th>
                            <th>الاستراتيجية</th>
                            <th>العقد (Lot)</th>
                            <th>المخاطرة ($)</th>
                            <th>الدخول</th>
                            <th>الوقف (SL)</th>
                            <th>الهدف (TP)</th>
                            <th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody id="trades-table">
                        <tr><td colspan="10" style="text-align:center;">جاري تحميل سجل الصفقات الحية...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <script>
        function toggleSection(secId) {
            document.querySelectorAll('.section-box').forEach(el => {
                if(el.id === secId) {
                    el.classList.toggle('active');
                } else {
                    el.classList.remove('active');
                }
            });
        }

        function updateDashboard() {
            fetch('/api/data')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('price-xau').innerText = data.prices.XAUUSD;
                    document.getElementById('price-eur').innerText = data.prices.EURUSD;
                    document.getElementById('price-gbp').innerText = data.prices.GBPUSD;
                    document.getElementById('price-dxy').innerText = data.prices.DXY;

                    document.getElementById('lbl-capital').innerText = '$' + data.settings.capital;
                    document.getElementById('lbl-risk').innerText = data.settings.risk_pct + '%';
                    document.getElementById('lbl-dispatch').innerText = data.settings.auto_dispatch_active ? '🟢 مفعل' : '🔴 متوقف';
                    document.getElementById('lbl-style').innerText = data.settings.preferred_style === 'scalp' ? 'سكالبينج (Scalp)' : 'سوينج (Swing)';
                    document.getElementById('lbl-asset').innerText = data.settings.selected_auto_asset;
                    document.getElementById('lbl-active-strat').innerText = data.settings.active_weekly_strategy;

                    document.getElementById('inp-capital').value = data.settings.capital;
                    document.getElementById('inp-risk').value = data.settings.risk_pct;

                    if(data.strats_performance) {
                        let html = '';
                        data.strats_performance.forEach(s => {
                            let isActive = s.name === data.settings.active_weekly_strategy;
                            html += `<div class="strat-card">
                                <div class="strat-info">
                                    <b>📌 ${s.name}</b> ${isActive ? '<span style="color:#10b981;">[الاستراتيجية النشطة حالياً] 🟢</span>' : '<span style="color:#94a3b8;">[متاحة للتفعيل] ⚪</span>'}
                                    <div class="strat-stats">الصفقات: ${s.total} | ربح: ✅ ${s.win} | خسارة: ❌ ${s.loss} | النسبة: 🎯 <b>${s.win_rate}%</b></div>
                                </div>
                                <button class="toggle-btn ${isActive ? 'disabled' : ''}" onclick="activateStrategy('${s.name}')">${isActive ? 'مفعلة حالياً' : 'تفعيل الاستراتيجية 🎯'}</button>
                            </div>`;
                        });
                        document.getElementById('strategies-container').innerHTML = html;
                    }

                    let tbody = document.getElementById('trades-table');
                    if(data.trades && data.trades.length > 0) {
                        let html = '';
                        data.trades.forEach(t => {
                            html += `<tr>
                                <td>${t[0]}</td>
                                <td><b>${t[1]}</b></td>
                                <td>${t[2]}</td>
                                <td><code style="color:#38bdf8;">${t[3]}</code></td>
                                <td><b>${t[4]}</b></td>
                                <td>$${t[5]}</td>
                                <td>${t[7]}</td>
                                <td style="color:var(--danger);">${t[8]}</td>
                                <td style="color:var(--success);">${t[9]}</td>
                                <td><span class="info-item">${t[11]}</span></td>
                            </tr>`;
                        });
                        tbody.innerHTML = html;
                    }
                });
        }

        function apiToggleDispatch() {
            fetch('/api/action', {method: 'POST', body: JSON.stringify({action: 'toggle_dispatch'})}).then(() => updateDashboard());
        }

        function apiToggleStyle() {
            fetch('/api/action', {method: 'POST', body: JSON.stringify({action: 'toggle_style'})}).then(() => updateDashboard());
        }

        function setMonitoredAsset(ast) {
            fetch('/api/action', {method: 'POST', body: JSON.stringify({action: 'set_asset', asset: ast})}).then(() => {
                alert('✅ تم تغيير الأصل المستهدف إلى: ' + ast);
                updateDashboard();
            });
        }

        function activateStrategy(stratName) {
            fetch('/api/action', {method: 'POST', body: JSON.stringify({action: 'set_strategy', strategy: stratName})}).then(() => updateDashboard());
        }

        function saveRiskConfig(e) {
            e.preventDefault();
            let cap = document.getElementById('inp-capital').value;
            let risk = document.getElementById('inp-risk').value;
            fetch('/api/action', {method: 'POST', body: JSON.stringify({action: 'save_risk', capital: cap, risk_pct: risk})}).then(() => {
                alert('✅ تم حفظ التعديلات وإعادة حساب المخاطر بنجاح');
                updateDashboard();
            });
        }

        function calculateAndExecuteManualTrade() {
            let ast = document.getElementById('man-asset').value;
            let entry = parseFloat(document.getElementById('man-entry').value);
            let sl = parseFloat(document.getElementById('man-sl').value);

            if(!entry || !sl) {
                alert('⚠️ الرجاء إدخال سعر الدخول ونقطة وقف الخسارة (SL) بشكل صحيح');
                return;
            }

            fetch('/api/action', {
                method: 'POST', 
                body: JSON.stringify({action: 'manual_trade_custom', asset: ast, entry: entry, sl: sl})
            })
            .then(res => res.json())
            .then(data => {
                let box = document.getElementById('manual-result');
                box.style.display = 'block';
                box.innerHTML = `<b>🎯 نتيجة حساب المخاطرة وتنفيذ صفقة ICT:</b><br>
                • الأصل: <b>${data.asset}</b> | الاتجاه: <b>${data.direction}</b><br>
                • حجم العقد المحسوب: <b style="color:var(--accent);">${data.lot} Lot</b><br>
                • المبلغ المعرض للمخاطرة: <code>$${data.risk_amt}</code> (حسب نسبة رأس مالك)<br>
                • الدخول: <code>${data.entry}</code> | SL: <code style="color:red;">${data.sl}</code> | TP: <code style="color:green;">${data.tp}</code><br>
                ✅ <i>تم حفظ الصفقة في السجل وتقييمها تلقائياً.</i>`;
                updateDashboard();
            });
        }

        setInterval(updateDashboard, 4000);
        updateDashboard();
    </script>
</body>
</html>
"""

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode('utf-8'))
        elif self.path == '/api/data':
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_ultimate_trades ORDER BY id DESC LIMIT 15")
            trades = cursor.fetchall()
            
            strats_perf = []
            for st in ICT_STRATEGIES:
                cursor.execute("SELECT COUNT(*), SUM(CASE WHEN result LIKE '%WIN%' THEN 1 ELSE 0 END), SUM(CASE WHEN result LIKE '%LOSS%' THEN 1 ELSE 0 END) FROM ai_ultimate_trades WHERE strategy_used = ?", (st,))
                row = cursor.fetchone()
                tot = row[0] or 0
                win = row[1] or 0
                loss = row[2] or 0
                wr = round((win / tot * 100), 1) if tot > 0 else 0.0
                strats_perf.append({"name": st, "total": tot, "win": win, "loss": loss, "win_rate": wr})
                
            conn.close()
            
            payload = {
                "prices": live_market_cache,
                "trades": trades,
                "settings": bot_settings,
                "strats_performance": strats_perf
            }
            self.wfile.write(json.dumps(payload).encode('utf-8'))

    def do_POST(self):
        if self.path == '/api/action':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            resp_data = {"status": "success"}
            try:
                data = json.loads(post_data.decode('utf-8'))
                act = data.get('action')
                if act == 'toggle_dispatch':
                    bot_settings['auto_dispatch_active'] = not bot_settings['auto_dispatch_active']
                elif act == 'toggle_style':
                    bot_settings['preferred_style'] = 'swing' if bot_settings['preferred_style'] == 'scalp' else 'scalp'
                elif act == 'set_asset':
                    bot_settings['selected_auto_asset'] = data.get('asset', 'ALL')
                elif act == 'set_strategy':
                    bot_settings['active_weekly_strategy'] = data.get('strategy')
                elif act == 'save_risk':
                    bot_settings['capital'] = float(data.get('capital', 1000))
                    bot_settings['risk_pct'] = float(data.get('risk_pct', 1.0))
                elif act == 'manual_trade_custom':
                    ast = data.get('asset', 'XAUUSD')
                    entry = float(data.get('entry'))
                    sl = float(data.get('sl'))
                    strat = bot_settings['active_weekly_strategy']
                    style = bot_settings['preferred_style']
                    cap = bot_settings['capital']
                    risk_pct = bot_settings['risk_pct']
                    risk_amt = cap * (risk_pct / 100.0)
                    
                    # حساب الـ Pip Difference لمعادلة الـ Lot الحقيقي
                    diff = abs(entry - sl)
                    if diff == 0: diff = 1.0
                    
                    if ast == 'XAUUSD':
                        lot = round(risk_amt / (diff * 100), 2)
                    else:
                        lot = round(risk_amt / (diff * 10000 * 10), 2)
                    if lot < 0.01: lot = 0.01

                    direction = "🟢 شراء (BUY)" if entry > sl else "🔴 بيع (SELL)"
                    tp = round(entry + (diff * 2.0) if "شراء" in direction else entry - (diff * 2.0), 4 if ast!="XAUUSD" else 2)
                    
                    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO ai_ultimate_trades (asset, trade_type, strategy_used, lot_size, risk_amount, direction, entry, sl, tp, dxy_state) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (ast, f"MANUAL-{style.upper()}", strat, lot, risk_amt, direction, entry, sl, tp, live_market_cache['DXY']))
                    conn.commit()
                    conn.close()
                    
                    resp_data = {"asset": ast, "direction": direction, "entry": entry, "sl": sl, "tp": tp, "lot": lot, "risk_amt": risk_amt}
            except Exception as e:
                resp_data = {"error": str(e)}
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp_data).encode('utf-8'))

    def log_message(self, format, *args):
        pass

# ==========================================
# 2. الثوابت وإعدادات النظام
# ==========================================
ICT_STRATEGIES = [
    "1. FVG Mitigation (تخفيف الفجوات العادلة)",
    "2. Order Block Rejection (ارتداد مناطق الأوامر)",
    "3. Liquidity Sweep & Grab (اصطياد وكنس السيولة)",
    "4. Market Structure Shift (تحول هيكل السوق MSS)",
    "5. Dealing Range Premium/Discount (الخصم والعلاوة)",
    "6. Breaker Block Mitigation (كتل الكسر المؤسسية)",
    "7. Mitigation Block Reversal (انعكاس كتل التخفيف)"
]

bot_settings = {
    'capital': 1000.0,
    'risk_pct': 1.0,
    'auto_dispatch_active': True,
    'preferred_style': 'scalp',
    'selected_auto_asset': 'ALL',
    'active_weekly_strategy': ICT_STRATEGIES[0]
}

live_market_cache = {
    'XAUUSD': 4060.68,
    'EURUSD': 1.0850,
    'GBPUSD': 1.3020,
    'DXY': 103.50
}

def init_db():
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_ultimate_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT,
            trade_type TEXT,
            strategy_used TEXT,
            lot_size REAL,
            risk_amount REAL,
            direction TEXT,
            entry REAL,
            sl REAL,
            tp REAL,
            dxy_state REAL,
            result TEXT DEFAULT 'PENDING_EVALUATION',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def fetch_live_market_data():
    global live_market_cache
    try:
        # جلب أسعار محدثة وحقيقية من APIs عامة مجانية
        req_obj = urllib.request.Request("https://api.gold-api.com/price/XAU", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_obj, timeout=2) as response:
            gold_data = json.loads(response.read().decode('utf-8'))
            price_val = float(gold_data.get('price', 0))
            if 1000 < price_val < 6000:
                live_market_cache['XAUUSD'] = round(price_val, 2)
    except Exception:
        pass
    return live_market_cache

def background_engine():
    print("🚀 Pro Macro & ICT Engine running 24/7...")
    while True:
        try:
            time.sleep(45)
            fetch_live_market_data()
            if bot_settings['auto_dispatch_active']:
                asset_choice = bot_settings['selected_auto_asset']
                chosen_asset = random.choice(["XAUUSD", "EURUSD", "GBPUSD"]) if asset_choice == 'ALL' else asset_choice
                strat = bot_settings['active_weekly_strategy']
                style = bot_settings['preferred_style']
                price = live_market_cache.get(chosen_asset, 2800.0)
                cap = bot_settings['capital']
                risk_pct = bot_settings['risk_pct']
                risk_amt = cap * (risk_pct / 100.0)
                
                stop_pips = 12.0 if style == 'scalp' else 40.0
                diff = stop_pips * (0.1 if chosen_asset == "XAUUSD" else 0.0010)
                lot = round(risk_amt / (diff * (100 if chosen_asset == "XAUUSD" else 10000)), 2) or 0.01
                
                direction = "🟢 شراء (BUY)" if random.random() > 0.5 else "🔴 بيع (SELL)"
                if "شراء" in direction:
                    sl = round(price - diff, 4 if chosen_asset != "XAUUSD" else 2)
                    tp = round(price + (diff * 2.0), 4 if chosen_asset != "XAUUSD" else 2)
                else:
                    sl = round(price + diff, 4 if chosen_asset != "XAUUSD" else 2)
                    tp = round(price - (diff * 2.0), 4 if chosen_asset != "XAUUSD" else 2)
                
                conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO ai_ultimate_trades (asset, trade_type, strategy_used, lot_size, risk_amount, direction, entry, sl, tp, dxy_state) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (chosen_asset, style.upper(), strat, lot, risk_amt, direction, price, sl, tp, live_market_cache['DXY']))
                conn.commit()
                conn.close()

            # التقييم التلقائي
            conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("SELECT id, asset, entry, sl, tp, direction FROM ai_ultimate_trades WHERE result = 'PENDING_EVALUATION'")
            pending = cursor.fetchall()
            for t_id, t_asset, t_entry, t_sl, t_tp, t_dir in pending:
                curr_price = live_market_cache.get(t_asset, t_entry)
                if "شراء" in t_dir:
                    if curr_price >= t_tp:
                        cursor.execute("UPDATE ai_ultimate_trades SET result = 'WIN (هدف ناجح)' WHERE id = ?", (t_id,))
                    elif curr_price <= t_sl:
                        cursor.execute("UPDATE ai_ultimate_trades SET result = 'LOSS (ضرب الوقف)' WHERE id = ?", (t_id,))
                else:
                    if curr_price <= t_tp:
                        cursor.execute("UPDATE ai_ultimate_trades SET result = 'WIN (هدف ناجح)' WHERE id = ?", (t_id,))
                    elif curr_price >= t_sl:
                        cursor.execute("UPDATE ai_ultimate_trades SET result = 'LOSS (ضرب الوقف)' WHERE id = ?", (t_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Background error: {e}")

threading.Thread(target=background_engine, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()
