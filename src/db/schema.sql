-- MARA Database Schema (SQLite)
-- Migration: 001_initial_schema

-- Users
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile TEXT NOT NULL,
    flow TEXT NOT NULL CHECK(flow IN ('growth', 'income')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolios
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    portfolio_type TEXT NOT NULL CHECK(portfolio_type IN ('current', 'recommended')),
    total_value REAL NOT NULL,
    holdings TEXT NOT NULL,  -- JSON string
    allocation TEXT NOT NULL,  -- JSON string
    metadata TEXT,  -- JSON string

    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE (user_id, snapshot_date, portfolio_type)
);

CREATE INDEX IF NOT EXISTS idx_portfolios_user_date
ON portfolios(user_id, snapshot_date);

-- Predictions
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    flow TEXT NOT NULL CHECK(flow IN ('growth', 'income')),
    prediction_date DATE NOT NULL,

    -- Input
    input_portfolio_id TEXT NOT NULL,

    -- Macro
    market_regime TEXT CHECK(market_regime IN ('bull', 'bear', 'sideways', 'volatile')),
    macro_insights TEXT,  -- JSON

    -- Strategy
    recommended_strategy TEXT,
    target_allocation TEXT,  -- JSON
    expected_return REAL,
    expected_volatility REAL,
    expected_sharpe REAL,
    expected_max_dd REAL,

    -- Rebalancing
    rebalancing_method TEXT,
    rebalancing_actions TEXT,  -- JSON

    -- Report
    report_markdown TEXT,
    report_path TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (input_portfolio_id) REFERENCES portfolios(portfolio_id)
);

CREATE INDEX IF NOT EXISTS idx_predictions_user_date
ON predictions(user_id, prediction_date);

-- Performance Results
CREATE TABLE IF NOT EXISTS performance_results (
    result_id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Period
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    -- Actual Performance
    actual_return REAL NOT NULL,
    actual_volatility REAL,
    actual_sharpe REAL,
    actual_max_dd REAL,

    -- Comparison
    return_error REAL NOT NULL,
    prediction_accuracy REAL NOT NULL,

    -- Details
    sector_performance TEXT,  -- JSON
    agent_attribution TEXT,  -- JSON

    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_results_prediction
ON performance_results(prediction_id);

-- Agent Performance
CREATE TABLE IF NOT EXISTS agent_performance (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,

    -- Stats
    total_predictions INTEGER DEFAULT 0,
    accurate_predictions INTEGER DEFAULT 0,
    accuracy_rate REAL DEFAULT 0.0,

    recent_accuracy REAL,

    -- Weights
    current_weight REAL NOT NULL,
    recommended_weight REAL,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE (user_id, agent_name)
);

-- Execution Logs
CREATE TABLE IF NOT EXISTS execution_logs (
    log_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    flow TEXT NOT NULL CHECK(flow IN ('growth', 'income')),
    execution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    layers_completed TEXT,  -- JSON array

    error_message TEXT,
    execution_time_seconds INTEGER,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Agent Predictions (Layer별 Agent 개별 예측)
CREATE TABLE IF NOT EXISTS agent_predictions (
    agent_prediction_id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Agent 정보
    layer TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_persona TEXT,
    agent_weight REAL,

    -- 예측 내용
    prediction_data TEXT NOT NULL,  -- JSON string

    -- Macro Layer 전용
    market_regime TEXT,
    sector_outlook TEXT,  -- JSON
    confidence_score REAL,

    -- Strategy Layer 전용
    recommended_allocation TEXT,  -- JSON
    expected_return REAL,
    expected_risk REAL,

    -- Research Layer 전용
    opportunities TEXT,  -- JSON

    -- Rebalancing Layer 전용
    suggested_actions TEXT,  -- JSON

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_predictions_prediction
ON agent_predictions(prediction_id);

CREATE INDEX IF NOT EXISTS idx_agent_predictions_layer_agent
ON agent_predictions(layer, agent_name);

-- Agent Evaluations (Agent별 성과 평가)
CREATE TABLE IF NOT EXISTS agent_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    agent_prediction_id TEXT NOT NULL,
    performance_result_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Agent 정보
    layer TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_persona TEXT,

    -- 평가 기간
    evaluation_date DATE NOT NULL,
    prediction_date DATE NOT NULL,

    -- Layer별 평가 지표
    accuracy_score REAL,

    -- Macro Layer 평가
    regime_accuracy REAL,
    sector_prediction_error TEXT,  -- JSON

    -- Strategy Layer 평가
    return_prediction_error REAL,
    risk_prediction_error REAL,
    allocation_similarity REAL,

    -- Research Layer 평가
    opportunity_hit_rate REAL,
    theme_performance TEXT,  -- JSON

    -- Rebalancing Layer 평가
    action_effectiveness REAL,
    timing_score REAL,

    -- 종합 평가
    overall_contribution REAL,
    rationale TEXT,

    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (agent_prediction_id) REFERENCES agent_predictions(agent_prediction_id),
    FOREIGN KEY (performance_result_id) REFERENCES performance_results(result_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_evaluations_agent
ON agent_evaluations(agent_name, evaluation_date);

-- Agent Personas (Agent Persona 정의)
CREATE TABLE IF NOT EXISTS agent_personas (
    persona_id TEXT PRIMARY KEY,
    persona_name TEXT UNIQUE NOT NULL,

    -- Persona 정보
    display_name TEXT NOT NULL,
    description TEXT,
    investment_philosophy TEXT,

    -- 적용 가능한 Layer
    applicable_layers TEXT,  -- JSON

    -- Persona 설정
    config_file TEXT,
    system_prompt_file TEXT,

    -- 기본 파라미터
    default_weight REAL,
    sensitivity TEXT,

    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- Seed Data
INSERT OR IGNORE INTO users (user_id, name, profile, flow) VALUES
('marv', 'Marv', 'growth', 'growth'),
('parents', 'Parents', 'income', 'income');

-- Seed Personas
INSERT OR IGNORE INTO agent_personas (persona_id, persona_name, display_name, description, applicable_layers, default_weight, sensitivity, is_active) VALUES
('geopolitical', 'geopolitical', 'Geopolitical Risk Analyst', 'CIA 지정학 전문가 관점', '["macro"]', 0.25, 'moderate', 1),
('sector_rotation', 'sector_rotation', 'Sector Rotation Specialist', '섹터 사이클 분석 전문', '["macro"]', 0.40, 'aggressive', 1),
('monetary', 'monetary', 'Monetary Policy Expert', '중앙은행 정책 분석', '["macro"]', 0.30, 'moderate', 1),
('ray_dalio', 'ray_dalio', 'Ray Dalio All Weather', '레이 달리오 리스크 패리티 전략', '["macro", "strategy"]', 0.30, 'conservative', 1),
('warren_buffett', 'warren_buffett', 'Warren Buffett Value Investing', '워렌 버핏 가치투자 원칙', '["research", "strategy"]', 0.25, 'conservative', 1),
('theme_investment', 'theme_investment', 'Thematic Investment', '테마 중심 투자 발굴', '["research"]', 0.30, 'moderate', 1);
