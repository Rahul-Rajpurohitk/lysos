-- Lysos Workbench Postgres schema (loaded on Postgres init)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================================
-- sessions
-- =====================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID,
    target_pathogen TEXT NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'design',
    autonomy        TEXT NOT NULL DEFAULT 'copilot',
    constraints     JSONB DEFAULT '[]',
    max_iterations  INTEGER DEFAULT 8,
    iteration       INTEGER DEFAULT 0,
    terminated      BOOLEAN DEFAULT FALSE,
    termination_reason TEXT,
    resistome_summary  JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_pathogen   ON sessions(target_pathogen);
CREATE INDEX IF NOT EXISTS idx_sessions_user       ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);


-- =====================================================================
-- candidates  (with 3072-dim Gemini Embedding 2 vector)
-- =====================================================================

CREATE TABLE IF NOT EXISTS candidates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES sessions(id) ON DELETE CASCADE,
    parent_id   UUID REFERENCES candidates(id) ON DELETE SET NULL,
    smiles      TEXT NOT NULL,
    inchi_key   TEXT,
    pathogen    TEXT NOT NULL,
    scores      JSONB DEFAULT '{}',
    affinity_kcal_mol REAL,
    similar_to  TEXT[],
    notes       TEXT[],
    embedding   vector(3072),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candidates_session    ON candidates(session_id);
CREATE INDEX IF NOT EXISTS idx_candidates_parent     ON candidates(parent_id);
CREATE INDEX IF NOT EXISTS idx_candidates_inchi      ON candidates(inchi_key);
-- ivfflat works for cosine — built when we have ≥ ~100 rows
-- CREATE INDEX idx_candidates_embedding ON candidates USING ivfflat (embedding vector_cosine_ops);


-- =====================================================================
-- agent_events  (replay log + branching anchor points)
-- =====================================================================

CREATE TABLE IF NOT EXISTS agent_events (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID REFERENCES sessions(id) ON DELETE CASCADE,
    iteration   INTEGER,
    event_type  TEXT NOT NULL,
    agent       TEXT,
    payload     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_events_session     ON agent_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_events_session_typ ON agent_events(session_id, event_type);


-- =====================================================================
-- tool_calls (full record of every tool invocation)
-- =====================================================================

CREATE TABLE IF NOT EXISTS tool_calls (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent        TEXT,
    tool_name    TEXT NOT NULL,
    args         JSONB,
    result       JSONB,
    error        TEXT,
    duration_ms  INTEGER,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool    ON tool_calls(tool_name);


-- =====================================================================
-- constraints (per-session user constraints)
-- =====================================================================

CREATE TABLE IF NOT EXISTS constraints (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES sessions(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    field       TEXT,
    value       JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_constraints_session ON constraints(session_id);


-- =====================================================================
-- Convenience view: best candidate per session
-- =====================================================================

CREATE OR REPLACE VIEW v_best_candidate AS
SELECT DISTINCT ON (session_id)
    session_id,
    id AS candidate_id,
    smiles,
    (scores->>'composite')::float AS composite,
    created_at
FROM candidates
ORDER BY session_id, (scores->>'composite')::float DESC NULLS LAST, created_at DESC;
