// FVG_DCA_Pro/static/js/bot_detail_coffin.js

let isFirstLoad = true;
let currentTimeframe = '5m'; // Coffin 默认 5m

function updateData() {
    $.get('/api/get_data/' + CURRENT_BOT_ID, function(data) {
        const s = data.state;
        const c = data.config;
        const g = data.global;
        const m = data.metrics;

        $('#bot-name-display').text(data.name);
        
        // 1. 基础信息 & K线更新
        $('#market-price').text('$' + parseFloat(g.market_price).toFixed(2));
        updateChartPrice(parseFloat(g.market_price)); // 更新 K 线

        $('#balance').text('$' + parseFloat(s.balance).toFixed(2));
        let locked = parseFloat(s.total_cost || 0);
        $('#locked-margin').text('$' + locked.toFixed(2));
        $('#status-msg').text(g.status_msg);
        $('#symbol-display').text(c.symbol);

        // 更新盈亏数据
        let dp = m.daily_stats ? m.daily_stats.profit : 0.0;
        $('#daily-profit').html(`<span class="${dp >= 0 ? 'text-success-bright' : 'text-danger-bright'}">$${dp.toFixed(2)}</span>`);
        let net = m.net_pnl || 0.0;
        let netClass = net >= 0 ? 'text-success-bright' : 'text-danger-bright';
        let netSign = net > 0 ? '+' : '';
        $('#total-net-pnl').html(`<span class="${netClass}">${netSign}$${net.toFixed(2)}</span>`);

        let fees = m.total_fees || 0.0;
        $('#total-fees').text('$' + fees.toFixed(2));
        
        if (g.is_running) {
            $('#btn-start').addClass('d-none');
            $('#btn-stop').removeClass('d-none');
        } else {
            $('#btn-start').removeClass('d-none');
            $('#btn-stop').addClass('d-none');
        }

        // === 2. 状态机展示 (Coffin 特有) ===
        let rawStage = s.stage || 'IDLE';
        let displayStage = rawStage;
        let badgeClass = 'bg-secondary';
        let bkDir = s.breakout_dir ? s.breakout_dir.toUpperCase() : "";
        let dirLabel = "";
        let txtLong = I18N.long ? I18N.long.split(' ')[0] : "做多"; 
        let txtShort = I18N.short ? I18N.short.split(' ')[0] : "做空";

        if (bkDir === 'long' || bkDir === 'LONG') dirLabel = ` 🟢 ${txtLong}`;
        else if (bkDir === 'short' || bkDir === 'SHORT') dirLabel = ` 🔴 ${txtShort}`;

        if (rawStage === 'IDLE') {
            displayStage = "😴 " + (I18N.scanning || "Scanning");
            badgeClass = 'bg-secondary text-muted border border-secondary';
        } else if (rawStage === 'BREAKOUT') {
            displayStage = `🚀 ${I18N.detected || "Breakout"}${dirLabel}`;
            badgeClass = 'bg-warning text-dark border border-warning fw-bold';
        } else if (rawStage === 'RETEST') {
            displayStage = `⏳ ${I18N.retest_entry || "Retest"}${dirLabel}`;
            badgeClass = 'bg-info text-dark border border-info fw-bold';
        } else if (rawStage === 'IN_POS') {
            let sym = c.symbol || "---";
            let mType = c.market_type === 'spot' ? (I18N.spot || '现货') : (I18N.future || '合约');
            let lev = c.leverage || 1;
            let dir = (s.direction || c.direction || 'long').toLowerCase();
            let dirText = (dir === 'short') ? (I18N.short ? I18N.short.split(' ')[0] : '做空') : (I18N.long ? I18N.long.split(' ')[0] : '做多');
            displayStage = `${I18N.current_position || "持仓中"} ${sym} ${mType} ${lev}x ${dirText}`;
            badgeClass = 'bg-success';
        }
        $('#stage-badge').text(displayStage).attr('class', `badge ${badgeClass}`);

        let currentPos = parseFloat(s.position_amt || 0);
        let lev = c.leverage || 1;
        let avg = parseFloat(s.avg_price || 0);
        let sl = parseFloat(s.stop_loss_price || 0);
        let extreme = parseFloat(s.extreme_price || 0);
        let dir = s.direction || c.direction || 'long';
        let isLong = (dir === 'long');

        if (Math.abs(currentPos) > 0 || rawStage === 'IN_POS') {
            $('#header-pos-badge').removeClass('d-none');
            $('#val-pos').text(currentPos);
            $('#val-avg').text(avg > 0 ? "$" + avg.toFixed(2) : '---');
            $('#val-lev').text(lev + 'x');
            
            if (extreme > 0) {
                const isChinese = (I18N.success === '成功'); 
                let label = isLong ? (isChinese ? '高' : 'HI') : (isChinese ? '低' : 'LO');
                $('#val-extreme').text(`${label}: $${extreme.toFixed(2)}`);
            } else {
                $('#val-extreme').text('---');
            }

            $('#cfg-leverage')
                .prop('disabled', true)
                .attr('title', I18N.please_close_position_first || "Please close position first");
        } else {
            $('#header-pos-badge').addClass('d-none');
            $('#val-avg').text('---');
            $('#val-lev').text(lev + 'x');
            $('#val-extreme').text('---');

            if (c.market_type !== 'spot') {
                $('#cfg-leverage').prop('disabled', false).removeAttr('title');
            }
        }

        if (s.coffin_5m) {
            $('#box-5m').text(`$${s.coffin_5m.bottom.toFixed(2)} - $${s.coffin_5m.top.toFixed(2)}`);
        }
        
        let slText = "---";
        let slClass = "text-danger"; 

        if (sl > 0) {
            let isBE = false;
            if (currentPos > 0 && sl >= avg) isBE = true;
            else if (currentPos < 0 && sl <= avg) isBE = true;

            if (isBE) {
                slText = `$${sl.toFixed(2)} (SL to BE)`;
                slClass = "text-success-bright";
            } else {
                slText = `$${sl.toFixed(2)} (SL)`;
                slClass = "text-danger";
            }
        }
        $('#current-sl').text(slText).removeClass('text-danger text-success-bright').addClass(slClass);

        let pnl = m.pnl || 0;
        let pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
        $('#pos-pnl').html(`<span class="${pnlClass}">${pnl > 0 ? '+':''}$${pnl.toFixed(2)}</span>`);

        $('#cfg-capital').val(c.capital);
        if (isFirstLoad) {
            $('#cfg-direction').val(c.direction || 'long');
            $('#cfg-market-type').val(c.market_type || 'future');
            $('#cfg-leverage').val(c.leverage || 1);
            $('#cfg-be-trigger').val(c.be_trigger || 0.5);
            $('#cfg-trailing-gap').val(c.trailing_gap || 1.0);
            $('#cfg-retest-tol').val(c.retest_tolerance || 0.1);
            $('#cfg-close-action').val(c.manual_close_action || 'stop');
            $('#cfg-cooldown').val(c.cooldown_seconds !== undefined ? c.cooldown_seconds : 60);
            $('#cfg-order-amount').val(c.order_amount || 0);
            $('#cfg-amount-precision').val(c.amount_precision || 0.001);
            if (c.market_type === 'spot') {
                $('#cfg-leverage').val(1).prop('disabled', true).addClass('bg-dark text-muted');
            }
            commonLoadRsiData(c.rsi_conditions || []);
            $('#cfg-fee-rate').val(c.fee_rate !== undefined ? c.fee_rate : 0.05);

            $('#rsi_filter_stoch').prop('checked', c.rsi_filter_stoch === true);
            $('#rsi_filter_bb').prop('checked', c.rsi_filter_bb === true);
            $('#rsi_filter_adx').prop('checked', c.rsi_filter_adx === true);
            $('#rsi_filter_vol').prop('checked', c.rsi_filter_vol === true);

            if (c.ma_conditions && c.ma_conditions.length > 0) {
                commonLoadMaConditions(c.ma_conditions);
            } else {
                // 兼容旧数据的迁移逻辑
                if (c.ma_long_enabled) {
                    commonAddMaRow('long', {
                        tf: c.ma_long_tf,
                        period: c.ma_long_period,
                        ma_type: c.ma_long_type,
                        enabled: true
                    });
                }
                if (c.ma_short_enabled) {
                    commonAddMaRow('short', {
                        tf: c.ma_short_tf,
                        period: c.ma_short_period,
                        ma_type: c.ma_short_type,
                        enabled: true
                    });
                }
            }
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

function toggleBot(action) {
    commonToggleBot(CURRENT_BOT_ID, action, function() {
        updateData();
    });
}

function saveConfig() {
    const lev = parseFloat($('#cfg-leverage').val());
    if (lev < 1 || isNaN(lev)) return alert("❌ " + I18N.leverage_must_be_gte_1);

    let cooldown = parseInt($('#cfg-cooldown').val());
    if (isNaN(cooldown) || cooldown < 0) cooldown = 60; 

    let orderAmt = parseFloat($('#cfg-order-amount').val());
    if (isNaN(orderAmt) || orderAmt < 0) orderAmt = 0;

    let prec = parseFloat($('#cfg-amount-precision').val());
    if (isNaN(prec) || prec <= 0) prec = 0.001;

    let feeRate = parseFloat($('#cfg-fee-rate').val());
    if (isNaN(feeRate) || feeRate < 0) feeRate = 0.0005;

    const rsiConditions = commonGetRsiConditions();
    const maConditions = commonGetMaConditions();

    let data = {
        bot_id: CURRENT_BOT_ID,
        config: {
            direction: $('#cfg-direction').val(),
            market_type: $('#cfg-market-type').val(),
            capital: $('#cfg-capital').val(),
            order_amount: orderAmt,
            leverage: lev,
            be_trigger: $('#cfg-be-trigger').val(),
            trailing_gap: $('#cfg-trailing-gap').val(),
            retest_tolerance: $('#cfg-retest-tol').val(),
            manual_close_action: $('#cfg-close-action').val(),
            cooldown_seconds: cooldown,
            amount_precision: prec,
            rsi_conditions: rsiConditions,
            rsi_filter_stoch: $('#rsi_filter_stoch').is(':checked'),
            rsi_filter_bb: $('#rsi_filter_bb').is(':checked'),
            rsi_filter_adx: $('#rsi_filter_adx').is(':checked'),
            rsi_filter_vol: $('#rsi_filter_vol').is(':checked'),
            ma_conditions: maConditions,
            fee_rate: feeRate,
        }
    };
    $.ajax({
        url: '/api/update_config',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: (res) => alert(res.status === 'success' ? "✅ " + I18N.save + I18N.success : "❌ " + I18N.save + I18N.error)
    });
}

function manualClose() {
    commonManualClose(CURRENT_BOT_ID, function() {
        updateData();
    });
}

function manualBuy() {
    commonManualBuy(CURRENT_BOT_ID, '#manual-amt', function() {
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
    if (fileInput.files.length === 0) {
        return alert(I18N.please_upload_csv || "Please upload a CSV file first!");
    }
    
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
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

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