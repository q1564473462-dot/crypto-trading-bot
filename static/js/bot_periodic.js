// FVG_DCA_Pro/static/js/bot_periodic.js

let isFirstLoad = true;
let currentTimeframe = '1h'; // 默认 1h

function updateData() {
    $.get('/api/get_data/' + CURRENT_BOT_ID, function(data) {
        const s = data.state;
        const c = data.config;
        const g = data.global;
        const m = data.metrics;

        $('#bot-name-display').text(data.name);
        $('#market-price').text('$' + parseFloat(g.market_price).toFixed(2));
        updateChartPrice(parseFloat(g.market_price)); // Common

        $('#balance').text('$' + parseFloat(s.balance).toFixed(2));
        $('#status-msg').text(g.status_msg);
        $('#symbol-display').text(c.symbol);

        let dp = m.daily_stats ? m.daily_stats.profit : 0.0;
        $('#daily-profit').html(`<span class="${dp >= 0 ? 'text-success-bright' : 'text-danger-bright'}">$${dp.toFixed(2)}</span>`);
        
        let net = m.net_pnl || 0.0;
        let netClass = net >= 0 ? 'text-success-bright' : 'text-danger-bright';
        $('#total-net-pnl').html(`<span class="${netClass}">${net > 0 ? '+' : ''}$${net.toFixed(2)}</span>`);

        let fees = m.total_fees || 0.0;
        $('#total-fees').text('$' + fees.toFixed(2));

        if (g.is_running) {
            $('#btn-start').addClass('d-none');
            $('#btn-stop').removeClass('d-none');
        } else {
            $('#btn-start').removeClass('d-none');
            $('#btn-stop').addClass('d-none');
        }

        let avg = parseFloat(s.avg_price || 0);
        let amt = parseFloat(s.position_amt || 0);

        if (Math.abs(amt) > 0) {
             $('#cfg-leverage')
                .prop('disabled', true)
                .attr('title', I18N.please_close_position_first || "Please close position first");
        } else {
            if (c.market_type !== 'spot') {
                 $('#cfg-leverage').prop('disabled', false).removeAttr('title');
             }
        }

        let cost = parseFloat(s.total_cost || 0);
        $('#val-avg').text(avg > 0 ? "$" + avg.toFixed(2) : "---");
        $('#val-amt').text(amt.toFixed(5));
        $('#val-cost').text("$" + cost.toFixed(2));

        let pnl = m.pnl || 0;
        let pnlClass = pnl >= 0 ? 'text-success-bright' : 'text-danger-bright';
        $('#pos-pnl').html(`<span class="${pnlClass}">${pnl > 0 ? '+':''}$${pnl.toFixed(2)}</span>`);

        const lastT = parseFloat(s.last_invest_time || 0);
        const intervalH = parseFloat(c.interval_minutes || 60);
        if (lastT > 0 && g.is_running) {
            const nextT = new Date((lastT + intervalH * 60) * 1000);
            $('#next-time').text(formatTime(nextT));
        } else {
            $('#next-time').text("---");
        }

        if (isFirstLoad) {
            $('#cfg-direction').val(c.direction || 'long');
            $('#cfg-leverage').val(c.leverage || 1);
            $('#cfg-interval').val(c.interval_minutes || 60);
            $('#cfg-amount').val(c.invest_amount || 10);
            $('#cfg-price-limit').val(c.price_limit || 0);
            $('#cfg-close-action').val(c.manual_close_action || 'stop');
            $('#cfg-amount-precision').val(c.amount_precision || 0.001);
            commonLoadRsiData(c.rsi_conditions || []);

            $('#rsi_filter_stoch').prop('checked', c.rsi_filter_stoch === true);
            $('#rsi_filter_bb').prop('checked', c.rsi_filter_bb === true);
            $('#rsi_filter_adx').prop('checked', c.rsi_filter_adx === true);
            $('#rsi_filter_vol').prop('checked', c.rsi_filter_vol === true);

            // Long
            $('#ma_long_enabled').prop('checked', c.ma_long_enabled === true);
            $('#ma_long_tf').val(c.ma_long_tf || '15m');
            $('#ma_long_period').val(c.ma_long_period || 50);
            $('#ma_long_type').val(c.ma_long_type || 'ema');

            // Short
            $('#ma_short_enabled').prop('checked', c.ma_short_enabled === true);
            $('#ma_short_tf').val(c.ma_short_tf || '15m');
            $('#ma_short_period').val(c.ma_short_period || 50);
            $('#ma_short_type').val(c.ma_short_type || 'ema');

            isFirstLoad = false;
        }

        let logHtml = "";
        if (g.logs && g.logs.length > 0) {
            logHtml = g.logs.map(l => `<div class="border-bottom border-secondary py-1">${l}</div>`).join('');
        }
        $('#logs-container').html(logHtml);

        commonRenderRounds(g.rounds, c.leverage, c.symbol);
    });
}

function formatTime(date) {
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    const h = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    return `${m}-${d} ${h}:${min}`;
}

function toggleBot(action) {
    commonToggleBot(CURRENT_BOT_ID, action, function() {
        updateData();
    });
}

function saveConfig() {
    const lev = parseFloat($('#cfg-leverage').val());
    if (lev > 3) return alert("❌ " + I18N.leverage_max_3);

    let prec = parseFloat($('#cfg-amount-precision').val());
    if (isNaN(prec) || prec <= 0) prec = 0.001;

    const rsiConditions = commonGetRsiConditions();

    let data = {
        bot_id: CURRENT_BOT_ID,
        config: {
            direction: $('#cfg-direction').val(),
            leverage: lev,
            interval_minutes: $('#cfg-interval').val(),
            invest_amount: $('#cfg-amount').val(),
            price_limit: $('#cfg-price-limit').val(),
            manual_close_action: $('#cfg-close-action').val(),
            amount_precision: prec,
            
            rsi_conditions: rsiConditions,
            rsi_filter_stoch: $('#rsi_filter_stoch').is(':checked'),
            rsi_filter_bb: $('#rsi_filter_bb').is(':checked'),
            rsi_filter_adx: $('#rsi_filter_adx').is(':checked'),
            rsi_filter_vol: $('#rsi_filter_vol').is(':checked'),

            ma_long_enabled: $('#ma_long_enabled').is(':checked'),
            ma_long_tf: $('#ma_long_tf').val(),
            ma_long_period: parseInt($('#ma_long_period').val()) || 50,
            ma_long_type: $('#ma_long_type').val(),

            ma_short_enabled: $('#ma_short_enabled').is(':checked'),
            ma_short_tf: $('#ma_short_tf').val(),
            ma_short_period: parseInt($('#ma_short_period').val()) || 50,
            ma_short_type: $('#ma_short_type').val(),
        }
    };
    $.ajax({
        url: '/api/update_config',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: (res) => alert(res.status === 'success' ? "✅ " + I18N.config_saved : "❌ Error: " + res.msg)
    });
}

function manualBuy() {
    commonManualBuy(CURRENT_BOT_ID, '#manual-amt', function() {
        updateData();
    });
}

function manualClose() {
    commonManualClose(CURRENT_BOT_ID, function() {
        updateData();
    });
}

function executeDeposit() {
    commonExecuteDeposit(CURRENT_BOT_ID, '#deposit-amount', 'depositModal', function() {
        updateData();
    });
}

function addRsiRow(side) {
    commonAddRsiRow(side);
}

function checkBotMode() {
    $.get(`/api/get_data/${CURRENT_BOT_ID}`, function(res) {
        // [修改 1] 优先读取后端返回的 res.mode，其次是 URL 参数
        const isReplay = (res.mode === 'replay') || window.location.search.includes('mode=replay');
        
        if (isReplay) {
            // A. 切换控制区显示
            $('#live-controls').addClass('d-none');
            $('#replay-controls').removeClass('d-none');
            
            // 避免重复添加标签
            if ($('#bot-name-display .badge-info').length === 0) {
                 $('#bot-name-display').append(' <span class="badge bg-info badge-info">REPLAY</span>');
            }

            // [修改 2] 修正返回按钮链接
            const backBtn = document.getElementById('back-to-dashboard');
            if (backBtn) {
                // 修改 href，使其携带 mode=replay 参数
                backBtn.href = "/?mode=replay";
            }
        } else {
            // 实盘模式
            $('#live-controls').removeClass('d-none');
            $('#replay-controls').addClass('d-none');
        }
    });
}

function runBacktest() {
    const fileInput = document.getElementById('backtest-file');
    if (fileInput.files.length === 0) return alert(I18N.please_upload_csv || "Please upload a CSV file first!");
    
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('bot_id', CURRENT_BOT_ID);
    formData.append('file', file);
    
    const btn = $('#btn-run-backtest');
    const originalText = btn.text();
    btn.text("⏳ " + (I18N.running_dots || "Running...")).prop('disabled', true);
    
    $.ajax({
        url: '/api/start_backtest',
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function(res) {
            alert(res.status === 'success' ? res.msg : "Error: " + res.msg);
            if (res.status === 'success') location.reload();
        },
        error: () => alert(I18N.network_error_simple || "Network Error"),
        complete: () => btn.text(originalText).prop('disabled', false)
    });
}

document.addEventListener("DOMContentLoaded", function() {
    initCommonChart(function(tf) {
        currentTimeframe = tf;
        fetchCommonKline(CURRENT_BOT_ID, currentTimeframe);
    });
    fetchCommonKline(CURRENT_BOT_ID, currentTimeframe);

    commonInitMarketTypeListener();
    
    setInterval(() => {
        updateData();
        syncCommonCandleData(CURRENT_BOT_ID, currentTimeframe); 
    }, 3000);
    updateData();

    checkBotMode();
});