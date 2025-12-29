// FVG_DCA_Pro/static/js/dashboard.js

let availableSymbols = [];
let currentLayout = localStorage.getItem('dca_pro_layout') || 'strategy'; 

// === 1. 辅助格式化函数 ===

function fmtMoney(val) {
    if (val === undefined || val === null) return "---";
    return "$" + parseFloat(val).toFixed(2);
}

function fmtNum(val, dec=5) {
    if (val === undefined || val === null) return "---";
    return parseFloat(val).toFixed(dec);
}

function fmtPnl(val) {
    if (val === undefined) return "---";
    const v = parseFloat(val);
    const cls = v >= 0 ? "text-success-bright" : "text-danger-bright"; 
    return `<span class="${cls} fw-bold font-monospace">${v > 0 ? '+' : ''}$${v.toFixed(2)}</span>`;
}

// === 2. 初始化与渲染逻辑 ===

function switchLayout(layout) {
    currentLayout = layout;
    localStorage.setItem('dca_pro_layout', layout);
    $('.btn-group .btn').removeClass('active');
    $(`#btn-layout-${layout}`).addClass('active');
    $('.layout-container').removeClass('active');
    setTimeout(() => {
        $(`#layout-${layout}-container`).addClass('active');
    }, 50);
    renderDashboard();
}

function generateBotCardHtml(bot) {
    if (bot.strategy_type === 'coffin') {
        return renderCoffinCard(bot);
    } else if (bot.strategy_type === 'grid_dca') {
        return renderGridCard(bot);
    } else if (bot.strategy_type === 'periodic') { // [新增]
        return renderPeriodicCard(bot);
    } else {
        return renderFvgCard(bot); 
    }
}

// [优化] 菜单按钮样式：改为 btn-outline-secondary，增加辨识度
function getActionMenu(bot) {
    const toggleAction = bot.is_running ? 'stop' : 'start';
    const toggleLabel = bot.is_running ? (I18N.stop_bot || "Stop") : (I18N.start_bot || "Start");
    
    let moveItems = '';
    if (currentLayout === 'custom') {
        moveItems += `<li><hr class="dropdown-divider border-secondary"></li>`;
        moveItems += `<li><h6 class="dropdown-header text-secondary small py-1">📂 ${I18N.move_to || "Move to..."}</h6></li>`;
        if (bot.folder_id) {
             moveItems += `<li><a class="dropdown-item small" href="#" onclick="moveBot(${bot.id}, '')">${I18N.uncategorized}</a></li>`;
        }
        if (typeof ALL_FOLDERS !== 'undefined') {
            ALL_FOLDERS.forEach(f => {
                if (bot.folder_id !== f.id) {
                    moveItems += `<li><a class="dropdown-item small" href="#" onclick="moveBot(${bot.id}, ${f.id})">${f.name}</a></li>`;
                }
            });
        }
    }

    // [修改点] 按钮样式优化：btn-outline-secondary + 去除边框(视觉更干净但有hover效果) + 更大的省略号
    return `
    <div class="dropdown">
        <button class="btn btn-sm btn-outline-secondary border-0 text-light px-2" type="button" data-bs-toggle="dropdown" title="${I18N.actions}">
            <span class="fs-5 lh-1">⋮</span>
        </button>
        <ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end shadow border border-secondary" style="z-index: 1050;">
            <li>
                <a class="dropdown-item py-2" href="#" onclick="toggleBot(${bot.id}, '${toggleAction}')">
                    ${toggleLabel}
                </a>
            </li>
            <li>
                <a class="dropdown-item py-2 text-warning" href="#" onclick="manualClose(${bot.id})">
                    ${I18N.manual_close || "Close Position"}
                </a>
            </li>
            ${moveItems}
            <li><hr class="dropdown-divider border-secondary"></li>
            <li>
                <a class="dropdown-item py-2 text-danger" href="#" onclick="deleteBot(${bot.id})">
                    🗑️ ${I18N.delete}
                </a>
            </li>
        </ul>
    </div>`;
}

// [修复] 状态显示逻辑：避免重复图标
function getStatusHtml(bot) {
    let statusHtml = '';
    
    if (bot.is_running) {
        // 默认文本
        let text = (I18N.running || "Running");
        let cls = "text-success"; 
        
        const msg = bot.status_msg || "";
        // 判断是否为普通监控状态
        const isNormal = msg === "Monitoring" || msg === (I18N.status_monitoring || "Monitoring") || msg === "";
        
        if (!isNormal) {
            if (msg.includes("Error") || msg.includes("⚠️") || (I18N.error && msg.includes(I18N.error))) {
                text = msg;
                cls = "text-danger";
            } else if (msg.includes("Cooldown") || (I18N.status_cooldown && msg.includes(I18N.status_cooldown))) {
                // 冷却状态
                text = `${I18N.running} <span class="text-secondary small">(${msg})</span>`;
                cls = "text-warning";
            } else {
                // [修改点] 检查 msg 是否已经包含图标（如 🟢, 🟡 等），如果包含了就不加
                // 简单的检查方法：看第一个字符是否是非 ASCII 字符，或者直接用 includes
                const hasIcon = msg.includes("🟢") || msg.includes("🟡") || msg.includes("🛑") || msg.includes("🔴");
                if (hasIcon) {
                    text = msg; // 直接使用后端传来的带图标消息
                } else {
                    text = `🟢 ${msg}`; // 后端没图标，前端补一个
                }
            }
        } else {
            text = `🟢 ${text}`; // 普通运行状态
        }
        statusHtml = `<div class="small fw-bold ${cls} text-truncate mb-2" title="${msg}">${text}</div>`;
    } else {
        statusHtml = `<div class="small fw-bold text-danger mb-2">🔴 ${I18N.stopped || "Stopped"}</div>`;
    }
    return statusHtml;
}

function getCommonDataRow(bot) {
    return `
    <div class="row g-2 mb-2 text-center" style="font-size: 0.8rem;">
        <div class="col-6 border-end border-secondary border-opacity-25">
            <span class="text-secondary d-block small">${I18N.pos_avg || "Avg"}</span>
            <span class="text-warning fw-bold font-monospace">${fmtMoney(bot.avg_price)}</span>
        </div>
        <div class="col-6">
            <span class="text-secondary d-block small">${I18N.pos_amt || "Amt"}</span>
            <span class="text-light fw-bold font-monospace">${fmtNum(bot.pos_amt)}</span>
        </div>
        <div class="col-6 border-end border-secondary border-opacity-25 border-top pt-1 mt-1">
            <span class="text-secondary d-block small">${I18N.pos_cost || "Cost"}</span>
            <span class="text-light font-monospace">${fmtMoney(bot.total_cost)}</span>
        </div>
        <div class="col-6 border-top border-secondary border-opacity-25 pt-1 mt-1">
            <span class="text-secondary d-block small">${I18N.balance || "Balance"}</span>
            <span class="text-light font-monospace">${fmtMoney(bot.total_balance)}</span>
        </div>
    </div>`;
}

function getPnlBlock(bot) {
    const currentProfit = parseFloat(bot.current_profit || 0); 
    const floatingPnl = parseFloat(bot.floating_pnl || 0);
    const totalCost = parseFloat(bot.total_cost || 0);
    const netPnl = parseFloat(bot.net_pnl || 0);

    let pnlPct = 0;
    if (totalCost > 0) {
        pnlPct = (floatingPnl / totalCost * 100);
    }
    const pnlPctClass = pnlPct >= 0 ? 'text-success' : 'text-danger';
    const realizedClass = currentProfit >= 0 ? 'text-success' : 'text-danger';

    return `
    <div class="bg-black bg-opacity-25 rounded p-2 mb-2 border border-secondary border-opacity-10">
        <div class="d-flex justify-content-between align-items-center mb-1">
            <span class="text-secondary small">${I18N.floating_pnl}:</span>
            <div class="text-end lh-1">
                ${fmtPnl(floatingPnl)}
                <div class="${pnlPctClass} small" style="font-size: 0.7rem;">${pnlPct.toFixed(2)}%</div>
            </div>
        </div>
        <div class="d-flex justify-content-between align-items-center mb-1">
            <span class="text-secondary small">${I18N.realized_pnl}:</span>
            <span class="${realizedClass} font-monospace small">${currentProfit > 0 ? '+' : ''}$${currentProfit.toFixed(2)}</span>
        </div>
        <div class="border-top border-secondary border-opacity-25 my-1"></div>
        <div class="d-flex justify-content-between align-items-center">
            <span class="text-light small fw-bold">${I18N.net_pnl}:</span>
            ${fmtPnl(netPnl)}
        </div>
    </div>`;
}

function renderCoffinCard(bot) {
    const s = bot.strat_info || {};
    const c = bot.config || {};
    
    // --- 1. 数据准备 ---
    const balance = parseFloat(bot.total_balance || 0).toFixed(2);
    const capital = parseFloat(c.capital || 0).toFixed(0); 
    const netPnl = parseFloat(bot.net_pnl || 0);
    const floatPnl = parseFloat(bot.floating_pnl || 0);
    const realized = parseFloat(bot.current_profit || 0);
    const costVal = parseFloat(bot.total_cost || 0);
    
    let pnlPct = (costVal > 0) ? (floatPnl / costVal) * 100 : 0;
    
    const floatClass = floatPnl >= 0 ? 'text-success' : 'text-danger';
    const realClass = realized >= 0 ? 'text-success' : 'text-danger';
    const pnlPctClass = pnlPct >= 0 ? 'text-success' : 'text-danger';

    // --- 2. 状态标签 (中间栏) ---
    let dirText = "---";
    let dirClass = "bg-secondary";
    
    if (bot.direction) {
        const d = bot.direction.toUpperCase();
        if (d === 'SHORT') {
            dirText = I18N.short || '做空';
            dirClass = 'bg-danger';
        } else if (d === 'LONG') {
            dirText = I18N.long || '做多';
            dirClass = 'bg-success';
        } else {
            // 处理 Both 或其他状态
            dirText = I18N.both || '多空';
            dirClass = 'bg-warning text-dark';
        }
    }
    
    const isCN = (I18N.success === '成功');
    let stageLabel = s.stage || 'IDLE';
    if (s.stage === 'IDLE') stageLabel = isCN ? "扫描中" : "Scanning";
    else if (s.stage === 'BREAKOUT') stageLabel = isCN ? "监测到" : "Breakout";
    else if (s.stage === 'RETEST') stageLabel = isCN ? "回踩进场" : "Retest";
    else if (s.stage === 'IN_POS') stageLabel = isCN ? "持仓中" : "Position";

    // --- 3. 底部状态与价格 ---
    const isRunning = bot.is_running;
    let statusText = isRunning ? "🟢" + (I18N.running || "运行中") : "🔴" + (I18N.stopped || "已停止");
    let statusColor = isRunning ? "text-success" : "text-danger";
    
    if (isRunning && bot.status_msg) {
        if (bot.status_msg.includes("Cooldown") || bot.status_msg.includes("冷却")) {
            statusText = I18N.status_cooldown || "冷却中";
            statusColor = "text-warning";
        } else if (bot.status_msg.includes("Error")) {
            statusText = "Error";
            statusColor = "text-danger";
        }
    }

    // --- 4. 底部数据格式化 ---
    const amt = fmtNum(bot.pos_amt);
    const avg = fmtMoney(bot.avg_price);
    const sl = s.sl ? `$${parseFloat(s.sl).toFixed(2)}` : "---";
    const cost = fmtMoney(costVal);
    const extreme = s.extreme ? parseFloat(s.extreme).toFixed(2) : "---";
    let box5m = s.box_5m || "---";
    let boxStyle = box5m.length > 18 ? "font-size: 0.75rem;" : "font-size: 0.85rem;";

    // --- 自定义样式逻辑 ---
    const rightColor = netPnl >= 0 ? '#198754' : '#dc3545';
    const customCardStyle = `
        background: linear-gradient(110deg, #000000 55%, ${rightColor} 55.1%);
        border: 2px solid white;
        border-radius: 10px;
        padding: 8px 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    `;

    const labelAvailable = I18N.balance || "可用余额";
    const labelTotal = I18N.total_investment || "初始投入"; 
    const labelNetPnl = I18N.net_pnl || "净盈亏";
    const labelRound = "当前回合"; 

    return `
    <div class="col-md-4 mb-4">
        <div class="card bot-card h-100 text-light shadow-sm border-secondary" style="border-width:1px;">
            <div class="card-header d-flex justify-content-between align-items-center py-2 bg-dark bg-opacity-50 border-bottom border-secondary border-opacity-25">
                <div class="d-flex align-items-center overflow-hidden">
                    <span class="fs-5 me-2">⚰️</span>
                    <div class="text-truncate fw-bold text-light">${bot.name}</div>
                </div>
                ${getActionMenu(bot)}
            </div>
            
            <div class="card-body p-3">
                <div class="mb-3" style="${customCardStyle}">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="lh-1">
                            <div class="fs-5 fw-bold font-monospace text-white">
                                ${balance}<span class="text-white">/${capital}</span>
                            </div>
                            <div class="mt-1" style="font-size: 0.75rem;">
                                <span class="text-secondary">${labelAvailable}</span>
                                <span class="text-white fw-bold">/${labelTotal} (USDT)</span>
                            </div>
                        </div>
                        
                        <div class="text-end lh-1">
                            <div class="fs-5 fw-bold font-monospace text-white">
                                $${netPnl.toFixed(2)}
                            </div>
                            <div class="text-white fw-bold mt-1" style="font-size: 0.75rem;">
                                ${labelNetPnl} (Net)
                            </div>
                        </div>
                    </div>
                </div>

                <div class="row mb-3 text-center">
                    <div class="col-6 border-end border-secondary border-opacity-25">
                        <div class="fw-bold font-monospace ${floatClass}">
                            ${floatPnl>0?'+':''}$${floatPnl.toFixed(2)} 
                            <span class="${pnlPctClass} small" style="font-size:0.7em">${pnlPct.toFixed(2)}%</span>
                        </div>
                        <div class="text-secondary small" style="font-size: 0.7rem;">${I18N.floating_pnl || "浮动盈亏"}(PnL)</div>
                    </div>
                    <div class="col-6">
                        <div class="fw-bold font-monospace ${realClass}">${realized>0?'+':''}$${realized.toFixed(2)}</div>
                        <div class="text-secondary small" style="font-size: 0.7rem;">${I18N.realized_pnl || "已实现盈亏"}</div>
                    </div>
                </div>

                <div class="bg-dark bg-opacity-10 border border-secondary border-opacity-25 rounded p-2">
                    <div class="d-flex justify-content-center align-items-center gap-2 mb-2 pb-2 border-bottom border-secondary border-opacity-25">
                        <span class="text-secondary small" style="font-size: 0.8rem;">${labelRound}</span>
                        <span class="badge bg-dark border border-secondary text-info">${bot.symbol}</span>
                        
                        <span class="badge ${dirClass}">${dirText}</span>
                        <span class="badge bg-secondary text-light">${bot.leverage}x</span>
                        <span class="badge bg-secondary border border-secondary">${stageLabel}</span>
                    </div>

                    <div class="d-flex justify-content-between align-items-center mb-2 px-2 py-1 bg-black bg-opacity-25 rounded border border-secondary border-opacity-10">
                         <small class="text-secondary" style="font-size: 0.75rem;">📦 ${I18N.box_range_5m || "5m 箱体"}</small>
                         <span class="font-monospace text-info fw-bold" style="${boxStyle}">${box5m}</span>
                    </div>

                    <div class="row text-center g-2" style="font-size: 0.9rem;">
                        <div class="col-4">
                            <div class="text-light font-monospace fw-bold">${amt}</div>
                            <div class="text-secondary small" style="font-size: 0.65rem;">${I18N.pos_amt || "持仓数量"}</div>
                        </div>
                        <div class="col-4 border-start border-end border-secondary border-opacity-25">
                            <div class="text-warning font-monospace fw-bold">${avg}</div>
                            <div class="text-secondary small" style="font-size: 0.65rem;">${I18N.pos_avg || "持仓均价"}</div>
                        </div>
                        <div class="col-4">
                            <div class="text-danger font-monospace fw-bold">${sl}</div>
                            <div class="text-secondary small" style="font-size: 0.65rem;">${I18N.current_sl || "当前止损"}</div>
                        </div>
                        
                        <div class="col-12 my-0 border-top border-secondary border-opacity-10"></div>

                        <div class="col-6 border-end border-secondary border-opacity-25">
                            <div class="text-light font-monospace fw-bold">${cost}</div>
                            <div class="text-secondary small" style="font-size: 0.65rem;">${I18N.pos_cost || "持仓保证金"}</div>
                        </div>
                        <div class="col-6">
                            <div class="text-success font-monospace fw-bold">${extreme}</div>
                            <div class="text-secondary small" style="font-size: 0.65rem;">${I18N.extreme_value || "极值"}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card-footer py-2 bg-dark bg-opacity-75 d-flex justify-content-between align-items-center">
                <div class="d-flex align-items-center">
                    <div class="d-flex align-items-center me-3">
                        <span class="${statusColor} fw-bold small">${statusText}</span>
                    </div>
                    <div class="lh-1 border-start border-secondary border-opacity-25 ps-3">
                        <div class="text-warning font-monospace fw-bold">${fmtMoney(bot.market_price)}</div>
                        <div class="text-muted small" style="transform: scale(0.85); transform-origin: left center;">
                            ${I18N.market_price || "当前市价 (USD)"}
                        </div>
                    </div>
                </div>
                
                <a href="/bot/${bot.id}" class="btn btn-sm btn-outline-info rounded-pill px-4">
                    ${I18N.enter_details || "进入详情"} &rsaquo;
                </a>
            </div>
        </div>
    </div>`;
}

function renderFvgCard(bot) {
    const s = bot.strat_info || {};
    const dirClass = bot.direction === 'SHORT' ? 'bg-danger' : 'bg-success';
    const trailClass = s.is_trailing ? "text-warning fw-bold" : "text-secondary";
    const trailIcon = s.is_trailing ? "🔥" : "💤";

    // [逻辑修复] 只有激活追踪 (is_trailing=true) 且有极值时才显示价格，否则显示 ---
    const extremeDisplay = (s.is_trailing && s.extreme) ? fmtMoney(s.extreme) : '---';

    return `
    <div class="col-md-4 mb-4">
        <div class="card bot-card h-100 text-light shadow-sm border-warning" style="border-width:1px;">
            <div class="card-header d-flex justify-content-between align-items-center py-2 bg-dark bg-opacity-75">
                <div class="d-flex align-items-center overflow-hidden">
                    <span class="fs-5 me-2">📈</span>
                    <div class="text-truncate fw-bold text-warning">${bot.name}</div>
                </div>
                ${getActionMenu(bot)}
            </div>
            
            <div class="card-body p-3 d-flex flex-column">
                ${getStatusHtml(bot)}

                <div class="mb-3 d-flex gap-2">
                    <span class="badge ${dirClass}">${getDirText(bot.direction)}</span>
                    <span class="badge bg-secondary">${bot.leverage}x</span>
                </div>

                ${getCommonDataRow(bot)}
                ${getPnlBlock(bot)}

                <div class="mt-auto pt-2 small text-muted border-top border-secondary border-opacity-25">
                    <div class="d-flex justify-content-between align-items-center">
                        <span>${trailIcon} ${I18N.trail_status}: <span class="${trailClass}">${s.is_trailing ? (I18N.activated || "Active") : (I18N.not_activated || "Inactive")}</span></span>
                        <span>${I18N.trail_high || "High"}: <span class="text-light font-monospace">${extremeDisplay}</span></span>
                    </div>
                </div>
            </div>
            
            <div class="card-footer py-2 d-flex justify-content-between align-items-center bg-dark bg-opacity-50">
                <div class="lh-1">
                    <div class="text-warning fw-bold">${fmtMoney(bot.market_price)}</div>
                    <div class="text-muted" style="font-size: 0.65rem;">${I18N.market_price}</div>
                </div>
                <a href="/bot/${bot.id}" class="btn btn-sm btn-outline-warning rounded-pill px-3">${I18N.enter_details} &rsaquo;</a>
            </div>
        </div>
    </div>`;
}

function renderGridCard(bot) {
    const s = bot.strat_info || {};
    const dirClass = bot.direction === 'SHORT' ? 'bg-danger' : 'bg-success';
    const anchor = s.grid_anchor >= 0 ? `L${s.grid_anchor}` : "---";
    
    // 极值显示逻辑
    const extremeDisplay = (s.is_trailing && s.extreme) ? fmtMoney(s.extreme) : '---';
    
    // [新增] 定义追踪状态的样式和图标
    const trailClass = s.is_trailing ? "text-warning fw-bold" : "text-secondary";
    const trailIcon = s.is_trailing ? "🔥" : "💤";
    const trailText = s.is_trailing ? (I18N.activated || "Active") : (I18N.not_activated || "Inactive");

    return `
    <div class="col-md-4 mb-4">
        <div class="card bot-card h-100 text-light shadow-sm border-primary" style="border-width:1px;">
            <div class="card-header d-flex justify-content-between align-items-center py-2 bg-dark bg-opacity-75">
                <div class="d-flex align-items-center overflow-hidden">
                    <span class="fs-5 me-2">🔢</span>
                    <div class="text-truncate fw-bold text-primary">${bot.name}</div>
                </div>
                ${getActionMenu(bot)}
            </div>
            
            <div class="card-body p-3 d-flex flex-column">
                ${getStatusHtml(bot)}

                <div class="mb-3 d-flex gap-2">
                    <span class="badge ${dirClass}">${getDirText(bot.direction)}</span>
                    <span class="badge bg-secondary">${bot.leverage}x</span>
                </div>

                ${getCommonDataRow(bot)}
                ${getPnlBlock(bot)}

                <div class="mt-auto pt-2 small text-muted border-top border-secondary border-opacity-25">
                    <div class="mb-1">
                        <span>⚓ ${I18N.current_grid_anchor}: <span class="text-info fw-bold">${anchor}</span></span>
                    </div>
                    
                    <div class="d-flex justify-content-between align-items-center">
                        <span>${trailIcon} ${I18N.trail_status}: <span class="${trailClass}">${trailText}</span></span>
                        <span>🌊 ${I18N.trail_high || "High"}: <span class="text-light font-monospace">${extremeDisplay}</span></span>
                    </div>
                </div>
            </div>
            
            <div class="card-footer py-2 d-flex justify-content-between align-items-center bg-dark bg-opacity-50">
                <div class="lh-1">
                    <div class="text-warning fw-bold">${fmtMoney(bot.market_price)}</div>
                    <div class="text-muted" style="font-size: 0.65rem;">${I18N.market_price}</div>
                </div>
                <a href="/bot/${bot.id}" class="btn btn-sm btn-outline-primary rounded-pill px-3">${I18N.enter_details} &rsaquo;</a>
            </div>
        </div>
    </div>`;
}

function renderPeriodicCard(bot) {
    const dirClass = bot.direction === 'SHORT' ? 'bg-danger' : 'bg-success';
    // 定投不需要显示极值或复杂的网格信息，主要显示下次购买时间和间隔
    
    return `
    <div class="col-md-4 mb-4">
        <div class="card bot-card h-100 text-light shadow-sm border-secondary" style="border-width:1px;">
            <div class="card-header d-flex justify-content-between align-items-center py-2 bg-dark bg-opacity-75">
                <div class="d-flex align-items-center overflow-hidden">
                    <span class="fs-5 me-2">📅</span>
                    <div class="text-truncate fw-bold text-light">${bot.name}</div>
                </div>
                ${getActionMenu(bot)}
            </div>
            
            <div class="card-body p-3 d-flex flex-column">
                ${getStatusHtml(bot)}

                <div class="mb-3 d-flex gap-2">
                    <span class="badge ${dirClass}">${getDirText(bot.direction)}</span>
                    <span class="badge bg-secondary">${bot.leverage}x</span>
                </div>

                ${getCommonDataRow(bot)}
                ${getPnlBlock(bot)}
                
                <div class="mt-auto pt-2 small text-muted border-top border-secondary border-opacity-25">
                    <div class="text-truncate">${bot.status_msg || "Ready"}</div>
                </div>
            </div>
            
            <div class="card-footer py-2 d-flex justify-content-between align-items-center bg-dark bg-opacity-50">
                <div class="lh-1">
                    <div class="text-warning fw-bold">${fmtMoney(bot.market_price)}</div>
                    <div class="text-muted" style="font-size: 0.65rem;">${I18N.market_price}</div>
                </div>
                <a href="/bot/${bot.id}" class="btn btn-sm btn-outline-light rounded-pill px-3">${I18N.enter_details} &rsaquo;</a>
            </div>
        </div>
    </div>`;
}

function renderDashboard() {
    if (currentLayout === 'strategy') {
        renderStrategyLayout();
    } else {
        renderCustomLayout();
    }
}

function renderStrategyLayout() {
    const container = $('#layout-strategy-container');
    container.empty();

    const groups = {
        'fvg': { name: I18N.fvg_martingale, bots: [], icon: "📈" },
        'coffin': { name: I18N.coffin, bots: [], icon: "⚰️" },
        'grid_dca': { name: I18N.auto_grid, bots: [], icon: "🔢" }
    };

    ALL_BOTS.forEach(bot => {
        let type = bot.strategy_type || 'fvg';
        if (groups[type]) groups[type].bots.push(bot);
    });

    let html = '<div class="accordion" id="strategyAccordion">';
    
    Object.keys(groups).forEach((key, index) => {
        const group = groups[key];
        const collapseId = `collapse-${key}`;
        const show = 'show'; 
        const collapsed = '';

        html += `
        <div class="accordion-item bg-transparent border border-secondary mb-3 rounded overflow-hidden">
            <h2 class="accordion-header">
                <button class="accordion-button ${collapsed} shadow-none bg-dark text-light" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                    <span class="me-2 fs-5">${group.icon}</span>
                    <span class="me-2 fw-bold">${group.name}</span>
                    <span class="badge bg-secondary rounded-pill">${group.bots.length}</span>
                </button>
            </h2>
            <div id="${collapseId}" class="accordion-collapse collapse ${show}" data-bs-parent="#strategyAccordion">
                <div class="accordion-body bg-black bg-opacity-25 p-3">
                    <div class="row">
                        ${group.bots.length > 0 ? group.bots.map(generateBotCardHtml).join('') : `<div class="text-muted text-center py-3">${I18N.no_bot_instances}</div>`}
                    </div>
                </div>
            </div>
        </div>`;
    });

    html += '</div>';
    container.html(html);
}

function renderCustomLayout() {
    const container = $('#custom-folders-area');
    const uncategorizedArea = $('#uncategorized-area');
    container.empty();
    uncategorizedArea.empty();

    if (typeof ALL_FOLDERS === 'undefined' || !ALL_FOLDERS) {
        container.html('<div class="text-danger">Error: Folders data not loaded. Check backend.</div>');
        return;
    }

    let folderHtml = '';
    ALL_FOLDERS.forEach((folder) => {
        const folderBots = ALL_BOTS.filter(b => b.folder_id === folder.id);
        const collapseId = `folder-${folder.id}`;
        
        folderHtml += `
        <div class="accordion-item bg-transparent border border-secondary mb-3 rounded overflow-hidden">
            <h2 class="accordion-header d-flex align-items-center">
                <button class="accordion-button collapsed shadow-none flex-grow-1 bg-dark text-light" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                    <span class="me-2 fw-bold">📁 ${folder.name}</span>
                    <span class="badge bg-warning text-dark rounded-pill">${folderBots.length}</span>
                </button>
                <button class="btn btn-sm btn-link text-danger p-3 text-decoration-none bg-dark border-start border-secondary" onclick="deleteFolder(${folder.id})" title="${I18N.delete}">
                    ✕
                </button>
            </h2>
            <div id="${collapseId}" class="accordion-collapse collapse show" data-bs-parent="#custom-folders-area">
                <div class="accordion-body bg-black bg-opacity-25 p-3">
                    <div class="row">
                        ${folderBots.length > 0 ? folderBots.map(generateBotCardHtml).join('') : '<div class="text-muted text-center small">Empty Folder</div>'}
                    </div>
                </div>
            </div>
        </div>`;
    });
    container.html(folderHtml);

    const uncategorizedBots = ALL_BOTS.filter(b => !b.folder_id);
    if (uncategorizedBots.length > 0) {
        uncategorizedArea.html(uncategorizedBots.map(generateBotCardHtml).join(''));
    } else {
        uncategorizedArea.html(`<div class="col-12 text-center text-muted py-4 small">${I18N.all_bots_categorized || "All bots are categorized!"}</div>`);
    }
}

// === 4. 交互操作 (API) ===

$('#createFolderModal').on('show.bs.modal', function () {
    const container = $('#folder-bot-selection');
    container.empty();
    const uncategorized = ALL_BOTS.filter(b => !b.folder_id);
    
    if (uncategorized.length === 0) {
        container.html('<div class="text-muted small">No uncategorized bots available.</div>');
        return;
    }

    uncategorized.forEach(bot => {
        container.append(`
            <div class="form-check">
                <input class="form-check-input" type="checkbox" value="${bot.id}" id="chk-bot-${bot.id}">
                <label class="form-check-label small text-light" for="chk-bot-${bot.id}">
                    ${bot.name || bot.symbol} <span class="text-muted">(${bot.strategy_type})</span>
                </label>
            </div>
        `);
    });
});

function createFolder() {
    const name = $('#newFolderName').val().trim();
    if (!name) return alert(I18N.Please_provide_complete_information);

    const selectedBots = [];
    $('#folder-bot-selection input:checked').each(function() {
        selectedBots.push(parseInt($(this).val()));
    });

    $.ajax({
        url: '/api/create_folder',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ name: name, bot_ids: selectedBots }),
        success: function(res) {
            if (res.status === 'success') {
                location.reload(); 
            } else {
                alert(I18N.error + ": " + res.msg);
            }
        }
    });
}

function deleteFolder(id) {
    if (!confirm(I18N.delete_folder_confirm || "Delete this folder?")) return;
    $.ajax({
        url: '/api/delete_folder',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ folder_id: id }),
        success: function(res) {
            if (res.status === 'success') {
                location.reload();
            } else {
                alert(I18N.error + ": " + res.msg);
            }
        }
    });
}

function moveBot(botId, folderId) {
    let fid = folderId === "" ? null : parseInt(folderId);
    $.ajax({
        url: '/api/move_bot',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: botId, folder_id: fid }),
        success: function(res) {
            if (res.status === 'success') {
                const bot = ALL_BOTS.find(b => b.id === botId);
                if (bot) bot.folder_id = fid;
                renderCustomLayout(); 
            } else {
                alert(I18N.error + ": " + res.msg);
            }
        }
    });
}

function toggleBot(id, action) {
    $.ajax({
        url: '/api/toggle_bot',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: id, action: action }),
        success: function(res) {
            if (res.status === 'success') {
                updateDashboard();
            } else {
                alert(I18N.error + ": " + res.msg);
            }
        }
    });
}

function manualClose(id) {
    if(!confirm(I18N.manual_close_confirm || "Are you sure?")) return;
    $.ajax({
        url: '/api/manual_close',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ bot_id: id }),
        success: function(res) {
            if (res.status === 'success') {
                alert(res.msg);
                updateDashboard();
            } else {
                alert(I18N.error + ": " + res.msg);
            }
        }
    });
}

function createBot() {
    const name = $('#newName').val().trim();
    const symbol = $('#newSymbol').val().trim().toUpperCase();
    const capital = $('#newCapital').val();
    const sType = $('#newStrategyType').val(); 
    const mType = $('#newMarketType').val();

    const urlParams = new URLSearchParams(window.location.search);
    const currentMode = urlParams.get('mode') === 'replay' ? 'replay' : 'live';
    
    if(!symbol || !capital) return alert(I18N.Please_provide_complete_information);
    if(!symbol.includes('/')) return alert(I18N.Invalid_symbol_format);
    if (availableSymbols.length > 0 && !availableSymbols.includes(symbol)) {
        return alert("❌ " + (I18N.symbol_not_supported || "Symbol not supported"));
    }

    $.post('/api/add_bot', {name: name, symbol: symbol, capital: capital, strategy_type: sType, market_type: mType, mode: currentMode}, function(res) {
        if(res.status === 'success') {
            location.reload();
        } else {
            alert(I18N.Create_failed + ": " + res.msg);
        }
    }).fail(function() {
        alert(I18N.Network_request_failed);
    });
}

function deleteBot(id) {
    if(!confirm(I18N.delete_confirm_long)) return;
    $.post('/api/delete_bot', {bot_id: id}, function(res) {
        if(res.status === 'success') {
            location.reload();
        } else {
            alert(I18N.Delete_failed + ": " + res.msg);
        }
    }).fail(function() {
        alert(I18N.Network_request_failed);
    });
}

function loadSymbols() {
    const input = $('#newSymbol');
    const datalist = $('#symbolOptions');
    if (input.length === 0) return; 
    input.attr('placeholder', I18N.loading_symbol_list);

    $.get('/api/get_symbols', function(res) {
        if (res.status === 'success' && res.symbols && res.symbols.length > 0) {
            availableSymbols = res.symbols;
            datalist.empty(); 
            res.symbols.forEach(function(sym) {
                datalist.append(`<option value="${sym}">`);
            });
            input.attr('placeholder', I18N.search_symbol_placeholder);
            input.val('BTC/USDT'); 
        } else {
            handleSymbolError(input);
        }
    }).fail(function() {
        handleSymbolError(input);
    });
}

function handleSymbolError(element) {
    element.attr('placeholder', "❌ Connection Failed");
}

// === 5. 数据刷新与轮询 ===

function updateDashboard() {
    $.get('/api/get_dashboard_stats', function(data) {
        // 1. 更新数据
        data.forEach(freshBot => {
            const idx = ALL_BOTS.findIndex(b => b.id === freshBot.id);
            if (idx !== -1) {
                let fid = ALL_BOTS[idx].folder_id;
                Object.assign(ALL_BOTS[idx], freshBot);
                // 防止 folder_id 被覆盖为 undefined
                if (freshBot.folder_id === undefined) ALL_BOTS[idx].folder_id = fid;
            }
        });
        
        // 2. 渲染界面
        renderDashboard();
        
        // 3. [关键修改] 数据拿到并渲染后，才移除加载动画
        hidePageLoader();
        
    }).fail(function() {
        console.error("Dashboard update failed");
        // 即便网络出错，也不能让用户一直卡在加载页，还是得移除遮罩
        hidePageLoader();
    });
}

function getDirText(dir) {
    if (!dir) return "---";
    dir = dir.toLowerCase();
    // [修改] 直接返回翻译，不再截取字符串
    if (dir === 'long') return I18N.long || '做多';
    if (dir === 'short') return I18N.short || '做空';
    if (dir === 'both') return I18N.both || '多空';
    return dir.toUpperCase();
}

function hidePageLoader() {
    const loader = document.getElementById('page-loader');
    // 只有当 loader 存在且还没有隐藏时才执行
    if (loader && !loader.classList.contains('hidden')) {
        loader.classList.add('hidden'); // 触发淡出动画
        setTimeout(() => {
            loader.style.display = 'none'; // 动画结束后真正移除
        }, 500);
    }
}

// [新增] 下载数据逻辑
function startDownload() {
    const symbol = $('#dl-symbol').val();
    const tf = $('#dl-tf').val();
    const marketType = $('#dl-market-type').val();
    
    // [修改] 获取 start 和 end
    const start = $('#dl-start').val();
    const end = $('#dl-end').val();
    
    if(!start || !end) return alert(I18N.date_required || "Please select Start and End dates");
    if(start > end) return alert(I18N.end_date_must_be_later || "Start date cannot be after End date");
    
    const btn = $('#downloadDataModal .btn-primary');
    const oldText = btn.text();
    
    btn.text(I18N.downloading_wait || "Downloading...").prop('disabled', true);
    
    // [修改] 传递 end_date 代替 days
    fetch('/api/download_history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            symbol: symbol, 
            timeframe: tf, 
            start_date: start, 
            end_date: end,
            market_type: marketType
        })
    })
    .then(res => {
        if(res.ok) return res.blob();
        return res.json().then(err => { throw new Error(err.msg || "Download Error") });
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        // 文件名使用后端返回的 headers，或者这里简单构造
        a.download = `${symbol.replace('/','-')}_${marketType}_${tf}_${start}_to_${end}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        
        $('#downloadDataModal').modal('hide');
        alert(I18N.download_success_alert || "Success!");
    })
    .catch(err => {
        alert((I18N.download_error || "Error") + ": " + err.message);
    })
    .finally(() => {
        btn.text(oldText).prop('disabled', false);
    });
}

let dashboardInterval;
document.addEventListener("visibilitychange", function() {
    if (document.hidden) {
        clearInterval(dashboardInterval);
    } else {
        // 页面重新可见时，立即刷新一次，然后重启定时器
        updateDashboard();
        dashboardInterval = setInterval(updateDashboard, 3000);
    }
});

document.addEventListener("DOMContentLoaded", function() {
    loadSymbols();
    
    // 1. 先进行一次同步渲染（此时用的是页面刚加载时的 Jinja2 静态数据，可能含有 placeholders）
    switchLayout(currentLayout);

    // 2. [核心修改] 立即发起一次 AJAX 请求获取最新数据
    // 注意：不要在这里写 setTimeout(hidePageLoader)，因为我们要在 updateDashboard 的回调里才隐藏
    updateDashboard();

    // 3. 启动轮询（每 3 秒一次）
    dashboardInterval = setInterval(updateDashboard, 3000);
    
    // 4. [兜底策略] 万一接口彻底卡死超过 8 秒，强制移除遮罩，避免用户无法操作
    setTimeout(hidePageLoader, 8000);

    const urlParams = new URLSearchParams(window.location.search);
    const isReplay = urlParams.get('mode') === 'replay';
    const replayBtn = document.getElementById('replayModeToggle');
    const replayText = document.getElementById('replayModeText');
    if (replayBtn) {
        // 1. 根据当前 URL 状态初始化按钮显示
        if (isReplay) {
            // 使用 I18N 获取翻译，如果获取不到则使用默认值
            replayText.innerText = I18N.exit_replay_mode || "Exit Replay";
            
            // 改变按钮样式：变成绿色或者高亮，提示用户当前状态特殊
            replayBtn.classList.remove('btn-outline-warning');
            replayBtn.classList.add('btn-success');
            
            // 可选：给 body 加个标记，方便全局样式调整 (比如背景色微调)
            document.body.classList.add('mode-replay');
        }

        // 2. 绑定点击事件
        replayBtn.addEventListener('click', function(e) {
            e.preventDefault(); // 阻止 # 跳转

            if (isReplay) {
                // 如果当前是重播，点击则删除 mode 参数 -> 返回实盘
                urlParams.delete('mode');
            } else {
                // 如果当前是实盘，点击则添加 mode=replay -> 进入重播
                urlParams.set('mode', 'replay');
            }
            
            // 刷新页面，让后端重新渲染对应模式的数据
            window.location.search = urlParams.toString();
        });
    }

    const today = new Date().toISOString().split('T')[0];
    const endInput = document.getElementById('dl-end');
    if(endInput) endInput.value = today;
});