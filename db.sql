-- 1. 创建数据库
CREATE DATABASE IF NOT EXISTS crypto_bot_db DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE crypto_bot_db;

-- 2. 创建机器人实例表
-- 我们利用 JSON 类型字段来存储复杂的 config 和 state，
-- 这样你就不用改动原来代码里的字典结构，直接存进去即可。
CREATE TABLE IF NOT EXISTS bots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL COMMENT '交易对，如 BTC/USDT',
    is_running TINYINT(1) DEFAULT 0 COMMENT '0=停止, 1=运行',
    status_msg VARCHAR(255) DEFAULT '等待启动...' COMMENT '简短状态描述',
    
    -- 核心数据字段
    config_json LONGTEXT COMMENT '存储策略配置的 JSON 字符串',
    state_json LONGTEXT COMMENT '存储运行状态的 JSON 字符串',
    
    -- 下面这两个字段是为了方便在列表页快速展示，不用解析 JSON
    current_profit DECIMAL(20, 8) DEFAULT 0 COMMENT '当前持仓盈亏',
    total_balance DECIMAL(20, 8) DEFAULT 0 COMMENT '账户余额',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. 创建交易日志表
CREATE TABLE IF NOT EXISTS trade_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bot_id INT NOT NULL,
    log_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    action VARCHAR(50) COMMENT '买入/卖出/止损/止盈',
    price DECIMAL(20, 8),
    amount DECIMAL(20, 8),
    profit DECIMAL(20, 8) DEFAULT 0 COMMENT '平仓时的收益',
    note VARCHAR(255),
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
);

-- [新增] 1. 用户表
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS folders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 如果你已经有数据库了，请在 MySQL 客户端手动执行这句来升级结构：
ALTER TABLE bots ADD COLUMN user_id INT NOT NULL DEFAULT 1 AFTER id;
ALTER TABLE bots ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE bots ADD COLUMN strategy_type VARCHAR(20) DEFAULT 'fvg' AFTER symbol;

-- 1. 给 users 表增加 is_admin 字段 (0=普通用户, 1=管理员)
ALTER TABLE users ADD COLUMN is_admin TINYINT(1) DEFAULT 0;

-- 2. 将某个特定用户设置为管理员 (将 'your_admin_username' 替换为你的用户名)
UPDATE users SET is_admin = 1 WHERE username = 'your_admin_username';

-- 在 users 表中增加代理端口字段，默认为 0 (不使用代理)
ALTER TABLE users ADD COLUMN proxy_port INT DEFAULT 0;

-- 给 bots 表增加 name 字段，允许为空（兼容旧数据）
ALTER TABLE bots ADD COLUMN name VARCHAR(100) DEFAULT NULL COMMENT '机器人自定义名称' AFTER user_id;

-- 增加手续费字段，默认为 0
ALTER TABLE trade_logs ADD COLUMN fee DECIMAL(20, 8) DEFAULT 0 COMMENT '交易手续费';

-- 在 users 表中增加 language 字段，默认为简体中文
ALTER TABLE users ADD COLUMN language VARCHAR(10) DEFAULT 'zh-CN';

ALTER TABLE bots ADD COLUMN folder_id INT DEFAULT NULL;
ALTER TABLE bots ADD CONSTRAINT fk_bot_folder FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL;

ALTER TABLE users ADD COLUMN exchange_source VARCHAR(20) DEFAULT 'binance';

ALTER TABLE users ADD COLUMN api_key VARCHAR(255) DEFAULT NULL;
ALTER TABLE users ADD COLUMN api_secret VARCHAR(255) DEFAULT NULL;

ALTER TABLE users ADD COLUMN binance_api_key VARCHAR(255) DEFAULT NULL;
ALTER TABLE users ADD COLUMN binance_api_secret VARCHAR(255) DEFAULT NULL;

-- 给 bots 表增加 mode 字段，默认为 'live' (实盘)
ALTER TABLE bots ADD COLUMN mode VARCHAR(10) DEFAULT 'live';
-- 建议加个索引方便查询
CREATE INDEX idx_bot_mode ON bots(mode);