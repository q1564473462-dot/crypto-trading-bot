/**
 * static/js/bot_common.js
 * 存放所有策略通用的逻辑：K线图、RSI、交易记录渲染、API交互
 */

// --- 全局变量 (图表相关) ---
let commonChart = null;
let commonCandleSeries = null;
let commonCurrentBar = null;
let commonHasShownError = false;

// --- 工具函数 ---

// 简单的哈希函数 (用于对比数据是否变化)
function simpleHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = (hash << 5) - hash + char;
        hash |= 0; 
    }
    return hash;
}

// 时间格式化
function formatFullTime(ts) {
    if (!ts) return "---";
    if (String(ts).includes("进行中") || String(ts).includes("Running")) return ts;
    const date = new Date(ts);
    if (isNaN(date.getTime())) return String(ts);
    
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    const h = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    const s = String(date.getSeconds()).padStart(2, '0');
    return `${y}-${m}-${d} ${h}:${min}:${s}`;
}

function showNetworkError() {
    if (commonHasShownError) return;
    commonHasShownError = true;
    const title = (typeof I18N !== 'undefined' && I18N.network_error_title) || "⚠️ 网络连接失败";
    const msg = (typeof I18N !== 'undefined' && I18N.network_error_hint) || "无法连接服务器，请检查网络设置。";
    alert(title + "\n\n" + msg);
}

// --- K线图逻辑 ---

function initCommonChart(timeframeCallback) {
    const chartContainer = document.getElementById('tv-chart-container');
    if (!chartContainer) return;

    commonChart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: 350,
        layout: {
            background: { type: 'solid', color: '#000000' },
            textColor: '#d1d4dc',
        },
        grid: {
            vertLines: { color: 'rgba(42, 46, 57, 0.2)' },
            horzLines: { color: 'rgba(42, 46, 57, 0.2)' },
        },
        timeScale: {
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 12, 
            barSpacing: 10,
            minBarSpacing: 3,
        },
    });

    commonCandleSeries = commonChart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });
    
    window.addEventListener('resize', () => {
        commonChart.applyOptions({ width: chartContainer.clientWidth });
    });

    // 绑定时间周期切换事件
    $('#timeframe-select').change(function() {
        const tf = $(this).val();
        if (timeframeCallback) timeframeCallback(tf); // 通知外部重新拉取数据
    });
}

function fetchCommonKline(botId, timeframe) {
    if (!commonCandleSeries) return;
    $.get('/api/kline/' + botId + '?tf=' + timeframe + '&limit=1000', function(res) {
        if (res.status === 'success') {
            if (res.data && res.data.length > 0) {
                commonCandleSeries.setData(res.data);
                commonCurrentBar = res.data[res.data.length - 1];
            }
        } else {
            console.error("Kline fetch failed:", res.msg);
            showNetworkError();
        }
    }).fail(function() {
        console.error("Network request failed");
        showNetworkError();
    });
}

function syncCommonCandleData(botId, timeframe) {
    if (!commonCandleSeries) return;
    $.get('/api/kline/' + botId + '?tf=' + timeframe + '&limit=2', function(res) {
        if (res.status === 'success' && res.data.length > 0) {
            const latest = res.data[res.data.length - 1];
            
            if (!commonCurrentBar || latest.time !== commonCurrentBar.time) {
                commonCurrentBar = latest;
                commonCandleSeries.update(latest);
            } else {
                commonCurrentBar = {
                    ...commonCurrentBar,
                    open: latest.open,
                    high: Math.max(commonCurrentBar.high, latest.high),
                    low: Math.min(commonCurrentBar.low, latest.low),
                    // close 由实时 WebSocket 或 updateChartPrice 驱动
                };
                commonCandleSeries.update(commonCurrentBar);
            }
        }
    });
}

// 用于在 updateData 中实时更新 K 线收盘价
function updateChartPrice(price) {
    if (commonCandleSeries && commonCurrentBar && price > 0) {
        const nextBar = {
            ...commonCurrentBar,
            close: price,
            high: Math.max(commonCurrentBar.high, price),
            low: Math.min(commonCurrentBar.low, price)
        };
        commonCandleSeries.update(nextBar);
        commonCurrentBar = nextBar;
    }
}

// --- RSI 表格逻辑 ---

function commonLoadRsiData(conditions) {
    const tbodyLong = $('#rsi-table-body-long');
    const tbodyShort = $('#rsi-table-body-short');
    tbodyLong.empty();
    tbodyShort.empty();
    
    if (!conditions || conditions.length === 0) return;

    conditions.forEach(c => {
        const side = c.pos_side || 'long';
        commonAddRsiRow(side, c);
    });
}

function commonAddRsiRow(side, data=null) {
    const tf = data ? data.tf : '15m';
    const op = data ? data.op : '<';
    const val = data ? data.val : 30;
    const enabled = data ? (data.enabled !== false) : true; // 默认为 true

    const targetId = (side === 'short') ? '#rsi-table-body-short' : '#rsi-table-body-long';
    const tbody = $(targetId);
    
    const rid = Date.now() + Math.random().toString(36).substr(2, 5);
    const checked = enabled ? 'checked' : '';
    
    const html = `
    <tr id="rsi-row-${rid}" data-side="${side}">
        <td>
            <select class="form-select form-select-sm bg-black text-light border-secondary rsi-tf">
                <option value="5m" ${tf=='5m'?'selected':''}>5m</option>
                <option value="15m" ${tf=='15m'?'selected':''}>15m</option>
                <option value="1h" ${tf=='1h'?'selected':''}>1h</option>
                <option value="4h" ${tf=='4h'?'selected':''}>4h</option>
                <option value="1d" ${tf=='1d'?'selected':''}>1d</option>
            </select>
        </td>
        <td>
            <select class="form-select form-select-sm bg-black text-light border-secondary rsi-op">
                <option value="<" ${op=='<'?'selected':''}>&lt; </option>
                <option value=">" ${op=='>'?'selected':''}>&gt; </option>
            </select>
        </td>
        <td>
            <input type="number" class="form-control form-control-sm bg-black text-light border-secondary rsi-val" value="${val}">
        </td>
        <td class="text-center">
            <div class="form-check d-flex justify-content-center">
                <input class="form-check-input rsi-enabled" type="checkbox" ${checked}>
            </div>
        </td>
        <td class="text-end">
            <button class="btn btn-link text-secondary p-0" onclick="$('#rsi-row-${rid}').remove()">✕</button>
        </td>
    </tr>`;
    tbody.append(html);
}

function commonGetRsiConditions() {
    const rsiConditions = [];
    
    $('#rsi-table-body-long tr').each(function() {
        const row = $(this);
        rsiConditions.push({
            tf: row.find('.rsi-tf').val(),
            op: row.find('.rsi-op').val(),
            val: parseFloat(row.find('.rsi-val').val()) || 0,
            enabled: row.find('.rsi-enabled').is(':checked'),
            pos_side: 'long'
        });
    });

    $('#rsi-table-body-short tr').each(function() {
        const row = $(this);
        rsiConditions.push({
            tf: row.find('.rsi-tf').val(),
            op: row.find('.rsi-op').val(),
            val: parseFloat(row.find('.rsi-val').val()) || 0,
            enabled: row.find('.rsi-enabled').is(':checked'),
            pos_side: 'short'
        });
    });
    
    return rsiConditions;
}

// --- 交易记录渲染 (Render Rounds) ---

function commonRenderRounds(rounds, leverage = 1, symbol = "") {
    const container = $('#rounds-container');
    
    let baseCoin = "Units";
    if (symbol && symbol.includes('/')) {
        baseCoin = symbol.split('/')[0];
    } else if (symbol) {
        baseCoin = symbol;
    }

    if (!rounds || rounds.length === 0) {
        container.html(`<div class="text-center text-muted mt-4 small">${I18N.no_trade_records}</div>`);
        return;
    }

    let html = '<div class="accordion accordion-flush" id="roundsAccordion">';
    
    rounds.forEach((round) => {
        // [修改 1] 优先使用后端计算好的净利润 (net_profit)
        // 如果后端还没更新，回退到 profit (毛利)
        let finalProfit = (round.net_profit !== undefined) ? round.net_profit : round.profit;
        
        let profitClass = 'text-secondary';
        let profitSign = '';
        if (finalProfit > 0) { profitClass = 'text-success-bright'; profitSign = '+'; }
        else if (finalProfit < 0) { profitClass = 'text-danger-bright'; }
        
        let bgClass = 'bg-black';
        if (round.result === 'running') bgClass = 'bg-dark bg-opacity-25';

        let timeDisplay = formatFullTime(round.end_time);
        const collapseId = `flush-collapse-${round.round_id}`;
        
        let profitDisplay = round.result === 'running' 
            ? (I18N.status_running || "Running") 
            : `${profitSign}$${parseFloat(finalProfit).toFixed(4)}`;

        html += `
            <div class="accordion-item ${bgClass} border-bottom border-secondary">
                <h2 class="accordion-header">
                    <button class="accordion-button collapsed bg-transparent text-light p-2 shadow-none" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                        <div class="d-flex justify-content-between w-100 align-items-center me-2">
                            <div class="d-flex align-items-center">
                                <span class="text-muted small me-2">#${round.round_id}</span>
                                <span class="small font-monospace">${timeDisplay}</span>
                            </div>
                            <span class="${profitClass} fw-bold font-monospace">
                                ${profitDisplay}
                            </span>
                        </div>
                    </button>
                </h2>
                <div id="${collapseId}" class="accordion-collapse collapse" data-bs-parent="#roundsAccordion">
                    <div class="accordion-body p-0">
                        <table class="table table-dark table-sm m-0 small border-0">
                            <tbody class="text-muted">
        `;
        
        round.trades.forEach(trade => {
            let actionColor = 'text-light';
            let actLower = trade.action.toLowerCase();
            let isBuy = false; // [新增] 标记是否为买入
            let isSell = false; // [新增] 标记是否为卖出

            if(actLower.includes('buy') || actLower.includes('long') || actLower.includes('补仓') || actLower.includes('首单') || actLower.includes('加仓') || actLower.includes('base')) {
                actionColor = 'text-info';
                isBuy = true;
            }
            if(actLower.includes('sell') || actLower.includes('short') || actLower.includes('平仓') || actLower.includes('close') || actLower.includes('止盈')) {
                actionColor = 'text-warning';
                isSell = true;
            }
            
            let feeDisplay = '';
            if (trade.fee && parseFloat(trade.fee) > 0) {
                feeDisplay = `<div class="text-secondary small" style="font-size: 0.8rem;">${I18N.fee || 'Fee'}: -$${parseFloat(trade.fee).toFixed(4)}</div>`;
            }

            // [修改 2] 计算并显示单笔交易的总 USDT 金额
            let tradePrice = parseFloat(trade.price);
            let tradeAmt = parseFloat(trade.amount);
            let totalUsdt = tradePrice * tradeAmt;

            // [修改 3] 动态决定显示文本：买入($) / 卖出($)
            let orderLabel = I18N.current_order_usdt || 'Order($)'; // 默认兜底
            if (isBuy) orderLabel = (I18N.log_buy || 'Buy') + "($)";
            else if (isSell) orderLabel = (I18N.log_sell || 'Sell') + "($)";

            html += `
                <tr>
                    <td class="ps-3 border-secondary" style="width: 35%; vertical-align: middle; font-size: 0.8rem;">${formatFullTime(trade.log_time)}</td>
                    <td class="border-secondary" style="vertical-align: middle;"><span class="${actionColor}">${trade.action.split(':')[0]}</span></td>
                    <td class="border-secondary text-end pe-3 font-monospace py-2">
                        <div class="text-light" style="font-size: 1rem;">$${tradePrice.toFixed(2)}</div>
                        <div class="text-secondary small" style="font-size: 0.85rem;">
                            ${I18N.amount || 'Amt'}: ${tradeAmt.toFixed(4)} <span class="text-muted">${baseCoin}</span>
                        </div>
                        <div class="text-info small" style="font-size: 0.85rem;">
                             ${orderLabel}: $${totalUsdt.toFixed(2)}
                        </div>
                        ${feeDisplay}
                    </td>
                </tr>
            `;
        });

        html += `</tbody></table></div></div></div>`;
    });
    
    html += '</div>';
    
    const openId = container.find('.accordion-collapse.show').attr('id');
    container.html(html);
    
    if (openId) {
        const target = $('#' + openId);
        if (target.length) {
            target.addClass('show');
            target.prev().find('.accordion-button').removeClass('collapsed');
        }
    }
}

// --- 通用操作 (按钮点击) ---

function commonToggleBot(botId, action, callback) {
    $.ajax({
        url: '/api/toggle_bot',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: botId, action: action }),
        success: function(res) { 
            if(callback) callback(res);
        },
        error: function(xhr) {
            alert((I18N.network_request_failed || "Network Error") + ": " + xhr.statusText);
        }
    });
}

function commonManualBuy(botId, amountInputId, callback) {
    let amt = $(amountInputId).val();
    if (!amt || parseFloat(amt) <= 0) return alert(I18N.please_enter_valid_manual_buy_amount || "请输入有效的金额");
    
    const btn = event.target;
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = I18N.placing_order || "下单中...";

    $.ajax({
        url: '/api/manual_buy',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: botId, amount: amt }),
        success: function(res) { 
            if(res.status === 'success') {
                alert(res.msg);
                $(amountInputId).val(''); 
                if(callback) callback();
            } else {
                alert("❌ " + (I18N.error || "Error") + ": " + res.msg);
            }
        },
        error: function() { 
            alert(I18N.network_request_failed || "网络请求失败");
        },
        complete: function() {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    });
}

function commonManualClose(botId, callback) {
    if(!confirm(I18N.manual_close_confirm || "确认手动平仓吗？")) return;
    const btn = event.target;
    btn.disabled = true;
    $.ajax({
        url: '/api/manual_close',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: botId }),
        success: function(res) { 
            if(res.status === 'success') {
                alert(res.msg); 
                if(callback) callback();
            } else {
                alert("❌ " + (I18N.error || "Error") + ": " + res.msg);
            }
            btn.disabled = false;
        },
        error: function() { 
            btn.disabled = false;
            alert(I18N.network_request_failed || "网络请求失败");
        }
    });
}

function commonExecuteDeposit(botId, amountInputId, modalId, callback) {
    const amt = $(amountInputId).val();
    if (!amt || parseFloat(amt) <= 0) return alert(I18N.please_enter_valid_deposit_amount || "请输入有效金额");
    
    const btn = event.target;
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = I18N.processing || "处理中...";

    $.ajax({
        url: '/api/deposit',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: botId, amount: amt }),
        success: function(res) {
            if (res.status === 'success') {
                alert(res.msg);
                $(amountInputId).val(''); 
                const modal = bootstrap.Modal.getInstance(document.getElementById(modalId));
                if(modal) modal.hide();
                if(callback) callback(); 
            } else {
                alert("❌ " + (I18N.deposit_failed || "充值失败") + ": " + res.msg);
            }
        },
        error: function(err) {
            alert(I18N.network_request_failed || "网络请求失败");
        },
        complete: function() {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    });
}

function commonInitMarketTypeListener() {
    const marketSelect = $('#cfg-market-type');
    const leverageInput = $('#cfg-leverage');
    
    function updateLeverageState() {
        const type = marketSelect.val();
        if (type === 'spot') {
            leverageInput.val(1); 
            leverageInput.prop('disabled', true); 
            leverageInput.addClass('bg-dark text-muted'); 
        } else {
            leverageInput.prop('disabled', false); 
            leverageInput.removeClass('bg-dark text-muted');
        }
    }
    marketSelect.change(updateLeverageState);
    updateLeverageState();
}

/**
 * 动态添加一行 MA 设置条件
 * @param {string} side 'long' | 'short'
 * @param {object|null} data 回显数据
 */
function commonAddMaRow(side, data = null) {
    const tbodyId = side === 'long' ? 'ma-table-body-long' : 'ma-table-body-short';
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return; // 容错，防止当前页面没有这个 Modal

    const rowId = 'ma-row-' + Date.now() + Math.random().toString(36).substr(2, 5);
    const tf = data ? data.tf : '15m';
    const period = data ? data.period : 50;
    const type = data ? data.ma_type : 'ema';
    const enabled = data ? (data.enabled !== false) : true; // 默认启用

    const tr = document.createElement('tr');
    tr.id = rowId;
    tr.className = "border-bottom border-secondary border-opacity-10";
    tr.innerHTML = `
        <td class="ps-2">
            <select class="form-select form-control-mini w-mini-tf ma-tf">
                <option value="1m" ${tf==='1m'?'selected':''}>1m</option>
                <option value="5m" ${tf==='5m'?'selected':''}>5m</option>
                <option value="15m" ${tf==='15m'?'selected':''}>15m</option>
                <option value="1h" ${tf==='1h'?'selected':''}>1h</option>
                <option value="4h" ${tf==='4h'?'selected':''}>4h</option>
                <option value="1d" ${tf==='1d'?'selected':''}>1d</option>
            </select>
        </td>
        <td>
            <input type="number" class="form-control form-control-mini w-mini-num ma-period" value="${period}" placeholder="50">
        </td>
        <td>
            <select class="form-select form-control-mini w-mini-type ma-type">
                <option value="ema" ${type==='ema'?'selected':''}>EMA</option>
                <option value="sma" ${type==='sma'?'selected':''}>SMA</option>
            </select>
        </td>
        <td class="text-center">
            <div class="form-check d-inline-block" style="min-height:0;">
                <input class="form-check-input ma-enabled" type="checkbox" ${enabled ? 'checked' : ''}>
            </div>
        </td>
        <td class="text-end pe-2">
            <button class="btn btn-link text-secondary p-0" onclick="document.getElementById('${rowId}').remove()" title="Delete">
                <span class="fs-6">&times;</span>
            </button>
        </td>
    `;
    tbody.appendChild(tr);
}

/**
 * 获取当前表格中的 MA 配置数据
 * @returns {Array} ma_conditions 数组
 */
function commonGetMaConditions() {
    let conditions = [];
    
    // 内部函数：抓取指定方向的所有行
    const scrape = (side) => {
        const tbodyId = side === 'long' ? 'ma-table-body-long' : 'ma-table-body-short';
        // 使用 jQuery 遍历 (前提是页面引入了 jQuery，bot_detail 通常都有)
        $(`#${tbodyId} tr`).each(function() {
            conditions.push({
                pos_side: side,
                tf: $(this).find('.ma-tf').val(),
                period: parseInt($(this).find('.ma-period').val()) || 50,
                ma_type: $(this).find('.ma-type').val(),
                enabled: $(this).find('.ma-enabled').is(':checked')
            });
        });
    };
    
    scrape('long');
    scrape('short');
    return conditions;
}

/**
 * 加载并回显 MA 配置数据
 * @param {Array} conditions 后端返回的配置数组
 */
function commonLoadMaConditions(conditions) {
    $('#ma-table-body-long').empty();
    $('#ma-table-body-short').empty();
    
    if (!conditions || conditions.length === 0) return;
    
    conditions.forEach(c => {
        const side = c.pos_side || 'long'; // 兼容旧数据，无方向则默认为 long
        commonAddMaRow(side, c);
    });
}