// 点击卡片时的交互逻辑
function selectOption(type, value, element) {
    if (type === 'lang') {
        $('#selected-lang').val(value);
        // 清除同组 active
        $(element).closest('.row').find('.lang-option').removeClass('active');
        
    } else if (type === 'exchange') {
        $('#selected-exchange').val(value);
        $(element).closest('.row').find('.lang-option').removeClass('active');

        // [新增] 切换交易所时，立即更新输入框内容
        updateExchangeView(value);
    }
    // 添加当前 active
    $(element).addClass('active');
}

function saveAllSettings() {
    const lang = $('#selected-lang').val();
    const exchange = $('#selected-exchange').val();

    const apiKey = document.getElementById('api-key').value.trim();
    const apiSecret = document.getElementById('api-secret').value.trim();
    
    const btn = $('#btn-save');
    const btnText = $('#btn-text');
    const spinner = $('#btn-spinner');

    btn.prop('disabled', true);
    btnText.text(I18N.processing || 'Saving...');
    spinner.removeClass('d-none');

    $.ajax({
        url: '/api/save_user_settings',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ lang: lang, exchange: exchange, api_key: apiKey, api_secret: apiSecret }),
        success: function (res) {
            if (res.status === 'success') {
                alert(I18N.config_saved || "Configuration Saved!");
                setTimeout(() => {
                    location.reload();
                }, 500);
            } else {
                alert("Error: " + res.msg);
                resetBtn();
            }
        },
        error: function () {
            alert("Network Error");
            resetBtn();
        }
    });

    function resetBtn() {
        btn.prop('disabled', false);
        btnText.text(I18N.save_settings);
        spinner.addClass('d-none');
    }
}

function updateExchangeView(exchange) {
    // 1. 从刚才 HTML 里加的隐藏域中取出对应的 Key/Secret
    let cachedKey = $('#cache-key-' + exchange).val() || '';
    let cachedSecret = $('#cache-secret-' + exchange).val() || '';

    // 2. 填入输入框
    $('#api-key').val(cachedKey);
    $('#api-secret').val(cachedSecret);

    // 3. 动态修改标题，提示当前正在编辑哪个交易所
    // 尝试获取语言包里的基础标题，去掉 emoji
    let titleBase = "API Configuration"; 
    if (typeof I18N !== 'undefined' && I18N.api_config_title) {
        titleBase = I18N.api_config_title.replace('🔑', '').replace('API', '').trim();
        // 这里的替换只是为了防止重复显示，简单处理即可
        if (I18N.api_config_title.includes("API")) titleBase = "API " + titleBase;
    }
    
    let prefix = (exchange === 'binance') ? "Binance" : "Pionex";

    // 组合新标题： "🔑 Binance API Configuration"
    $('#api-config-title').text(`🔑 ${prefix} ${titleBase}`);
    
    // 4. 给输入框闪烁一下背景色，提示用户数据变了
    $('#api-key, #api-secret').addClass('bg-secondary').delay(200).queue(function(next){
        $(this).removeClass('bg-secondary');
        next();
    });
}

$(document).ready(function() {
    let currentEx = $('#selected-exchange').val();
    if(currentEx) {
        updateExchangeView(currentEx);
    }
});