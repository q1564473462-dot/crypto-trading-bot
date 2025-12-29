// FVG_DCA_Pro/static/js/bot_grid_dca.js

let isFirstLoad = true;
let lastDataHash = ""; 
let pollingInterval = null;
let currentStratType = ""; 
let currentTimeframe = '15m';

function updateData() {
    $.get('/api/get_data/' + CURRENT_BOT_ID, function(data) {
        const price = parseFloat(data.global.market_price);
        if (price > 0) {
            $('#market-price').text('$' + price.toFixed(2)).removeClass('text-warning').addClass('text-light');
            updateChartPrice(price); // Common
        } else {
            $('#market-price').text(I18N.loading).addClass('text-warning');
        }

        const compareObj = {
            state: data.state,
            logs: data.global.logs,
            ladder: data.global.ladder_preview,
            status: data.global.status_msg,
            running: data.global.is_running,
            pnl: data.metrics.pnl 
        };
        
        const currentHash = simpleHash(JSON.stringify(compareObj));
        if (!isFirstLoad && currentHash === lastDataHash) return;
        lastDataHash = currentHash;

        const s = data.state;
        const c = data.config;
        const g = data.global;
        const m = data.metrics;
        
        currentStratType = data.strategy_type || (c.grid_count ? "grid_dca" : "fib_grid");

        $('#bot-name-display').text(data.name);

        if (currentStratType === 'grid_dca') {
            $('#strat-name').text("Auto Grid DCA");
            $('#strat-icon').text("🔢");
            $('#manual-range-group').addClass('d-none');
            $('#auto-range-group').removeClass('d-none');
            $('#display-range-top').val(parseFloat(s.range_top || 0).toFixed(2));
            $('#display-range-bottom').val(parseFloat(s.range_bottom || 0).toFixed(2));
        } else {
            $('#strat-name').text("Smart Fib-FVG Grid");
            $('#strat-icon').text("🧬");
            $('#manual-range-group').removeClass('d-none');
            $('#auto-range-group').addClass('d-none');
        }

        $('#status-msg')
            .text(g.status_msg)
            .removeClass('text-danger text-muted')
            .addClass(g.status_msg.includes(I18N.error) || g.status_msg.includes('⚠️') ? 'text-danger' : 'text-muted');

        $('#symbol-display').text(c.symbol);

        if (g.is_running) {
            $('#btn-start').addClass('d-none');
            $('#btn-stop').removeClass('d-none');
            $('#cfg-grid-count, #cfg-range-percent').prop('disabled', true);
        } else {
            $('#btn-start').removeClass('d-none');
            $('#btn-stop').addClass('d-none');
            $('#cfg-grid-count, #cfg-range-percent').prop('disabled', false);
        }

        $('#balance').text('$' + parseFloat(s.balance).toFixed(2));
        let dp = m.daily_stats ? m.daily_stats.profit : 0.0;
        $('#daily-profit').html(`<span class="${dp >=0 ? 'text-success-bright':'text-danger-bright'}">$${dp.toFixed(2)}</span>`);

        let net = m.net_pnl || 0.0;
        let netClass = net >= 0 ? 'text-success-bright' : 'text-danger-bright';
        let netSign = net > 0 ? '+' : '';
        $('#total-net-pnl').html(`<span class="${netClass}">${netSign}$${net.toFixed(2)}</span>`);

        let fees = m.total_fees || 0.0;
        $('#total-fees').text('$' + fees.toFixed(2));
        
        $('#cfg-capital').val(c.capital);

        if (isFirstLoad) {
            $('#cfg-symbol').val(c.symbol);
            $('#cfg-direction').val(c.direction || 'long');
            $('#cfg-market-type').val(c.market_type || 'future');
            $('#cfg-fee-rate').val(c.fee_rate || 0.0005);
            $('#cfg-amount-precision').val(c.amount_precision || 0.001);
            $('#cfg-tp-target').val(c.tp_target || 1.5);
            $('#cfg-trailing-dev').val(c.trailing_dev || 0.0);
            $('#cfg-range-top').val(c.range_top || 0);
            $('#cfg-range-bottom').val(c.range_bottom || 0);
            $('#cfg-range-percent').val(c.range_percent || 0.2);
            $('#cfg-grid-count').val(c.grid_count || 10);
            $('#cfg-grid-type').val(c.grid_type || 'arithmetic');
            $('#cfg-leverage').val(c.leverage || 1);
            $('#cfg-close-action').val(c.manual_close_action || 'stop');

            if (c.market_type === 'spot') {
                $('#cfg-leverage').val(1).prop('disabled', true).addClass('bg-dark text-muted');
            }

            $('#cfg-sl-percent').val(c.stop_loss_percent !== undefined ? c.stop_loss_percent : 0);
            $('#cfg-cooldown').val(c.cooldown_seconds !== undefined ? c.cooldown_seconds : 60);

            commonLoadRsiData(c.rsi_conditions || []);

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

        if (parseFloat(s.position_amt) != 0) {
            let dir = s.direction || c.direction || "long";
            if(parseFloat(s.position_amt) < 0) dir = "short";

            let dirText = dir.toUpperCase();
            if (dir === 'long') dirText = I18N.long ? I18N.long.split(' ')[0] : "做多";
            if (dir === 'short') dirText = I18N.short ? I18N.short.split(' ')[0] : "做空";

            $('#pos-direction').text(dirText).removeClass('bg-secondary bg-success bg-danger').addClass(dir=='long'?'bg-success':(dir=='short'?'bg-danger':'bg-secondary'));
                
            $('#pos-avg').text("$" + parseFloat(s.avg_price).toFixed(2));
            $('#pos-amt').text(parseFloat(s.position_amt).toFixed(5));
            $('#pos-cost').text("$" + parseFloat(s.total_cost).toFixed(2));
            
            let pnlClass = m.pnl >= 0 ? 'text-success-bright' : 'text-danger-bright';
            $('#pos-pnl').html(`<span class="${pnlClass}">${m.pnl >= 0 ? '+' : '-'}$${Math.abs(m.pnl).toFixed(2)}</span>`);
            $('#pos-pnl-pct').html(`<span class="${pnlClass}">${m.pnl_pct.toFixed(2)}%</span>`);
            
            $('#grid-level-display').text(`L${s.last_level_idx}`);

            if (s.is_trailing_active) {
                $('#trail-status').text("🔥 " + I18N.activated).addClass('text-warning').removeClass('text-muted');
                let extreme = dir == 'long' ? s.highest_price_seen : s.lowest_price_seen;
                if (!extreme || extreme == 0) extreme = price;
                $('#trail-high').text(parseFloat(extreme).toFixed(2));
            } else {
                $('#trail-status').text(I18N.not_activated).removeClass('text-warning').addClass('text-muted');
                $('#trail-high').text("---");
            }

            $('#cfg-leverage')
                .prop('disabled', true)
                .attr('title', I18N.please_close_position_first || "Please close position first");
        } else {
            $('#pos-direction').text(I18N.no_position).removeClass('bg-success bg-danger').addClass('bg-secondary');
            $('#pos-avg, #pos-amt, #pos-cost, #pos-pnl, #pos-pnl-pct').text("---");
            $('#grid-level-display').text("---");
            $('#trail-status').text(I18N.not_activated).removeClass('text-warning').addClass('text-muted');
            $('#trail-high').text("---");

            if (c.market_type !== 'spot') {
                $('#cfg-leverage').prop('disabled', false).removeAttr('title');
            }
        }

        let rows = "";
        if(g.ladder_preview && g.ladder_preview.length > 0) {
            g.ladder_preview.forEach(item => {
                let cls = "";
                if (item.status.includes(I18N.status_monitoring)) cls = "table-info text-dark fw-bold border-3 border-info";
                else if (item.status.includes(I18N.status_filled)) cls = "table-success text-dark";
                else if (item.status.includes(I18N.status_passed)) cls = "text-muted";
                let amt = item.amount || 0;
                rows += `<tr class="${cls}">
                    <td>${item.so}</td>
                    <td>$${item.price.toFixed(2)}</td>
                    <td>$${amt.toFixed(1)}</td>
                    <td>${item.drop ? item.drop.toFixed(2) : 0}%</td>
                    <td>${item.status}</td>
                </tr>`;
            });
        } else {
            rows = `<tr><td colspan='5' class='text-muted'>${I18N.no_data_or_waiting_for_range}</td></tr>`;
        }
        $('#ladder-body').html(rows);

        let logHtml = "";
        if (g.logs && g.logs.length > 0) {
            logHtml = g.logs.map(l => `<div class="border-bottom border-secondary py-1">${l}</div>`).join('');
        }
        $('#logs-container').html(logHtml);

        commonRenderRounds(g.rounds, 1, c.symbol);
    });
}

function toggleBot(action) {
    commonToggleBot(CURRENT_BOT_ID, action, function() {
        lastDataHash = "";
        updateData();
    });
}

function saveConfig() {
    const lev = parseFloat($('#cfg-leverage').val());
    if (lev < 1 || isNaN(lev)) return alert(`❌ ${I18N.leverage_must_be_gte_1}`);

    let cooldown = parseInt($('#cfg-cooldown').val());
    if (isNaN(cooldown) || cooldown < 0) cooldown = 60;

    const rsiConditions = commonGetRsiConditions();
    const maConditions = commonGetMaConditions();

    let data = {
        bot_id: CURRENT_BOT_ID,
        config: {
            symbol: $('#cfg-symbol').val(),
            direction: $('#cfg-direction').val(),
            capital: $('#cfg-capital').val(),
            market_type: $('#cfg-market-type').val(),
            fee_rate: $('#cfg-fee-rate').val(),
            amount_precision: $('#cfg-amount-precision').val(),
            tp_target: $('#cfg-tp-target').val(),
            trailing_dev: $('#cfg-trailing-dev').val(),
            range_top: $('#cfg-range-top').val(),
            range_bottom: $('#cfg-range-bottom').val(),
            range_percent: $('#cfg-range-percent').val(),
            grid_count: $('#cfg-grid-count').val(),
            grid_type: $('#cfg-grid-type').val(),
            leverage: lev,
            manual_close_action: $('#cfg-close-action').val(),
            stop_loss_percent: $('#cfg-sl-percent').val(),
            cooldown_seconds: cooldown,
            rsi_conditions: rsiConditions,
            rsi_filter_stoch: $('#rsi_filter_stoch').is(':checked'),
            rsi_filter_bb: $('#rsi_filter_bb').is(':checked'),
            rsi_filter_adx: $('#rsi_filter_adx').is(':checked'),
            rsi_filter_vol: $('#rsi_filter_vol').is(':checked'),
            ma_conditions: maConditions,
        }
    };
    $.ajax({
        url: '/api/update_config',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(res) { 
            if(res.status === 'success') {
                alert(`✅ ${I18N.save_settings}`);
                lastDataHash = ""; 
                updateData();
            }
            else alert(`${I18N.save_failed}: ` + res.msg);
        }
    });
}

function manualClose() {
    commonManualClose(CURRENT_BOT_ID, function() {
        lastDataHash = "";
        updateData();
    });
}

function manualBuy() {
    commonManualBuy(CURRENT_BOT_ID, '#manual-amt', function() {
        lastDataHash = "";
        updateData();
    });
}

function executeDeposit() {
    commonExecuteDeposit(CURRENT_BOT_ID, '#deposit-amount', 'depositModal', function() {
        lastDataHash = "";
        updateData();
    });
}

function addRsiRow(side) {
    commonAddRsiRow(side);
}

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(() => {
        updateData();
        syncCommonCandleData(CURRENT_BOT_ID, currentTimeframe); 
    }, 3000);
    updateData();
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

document.addEventListener("visibilitychange", function() {
    if (document.hidden) clearInterval(pollingInterval);
    else startPolling();
});

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

    checkBotMode();
});

startPolling();