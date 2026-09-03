-- 002: Create core tables (PRD §9)
-- No hash columns. Caching is vector similarity on text claim only.

CREATE TABLE claims (
    id            BIGSERIAL PRIMARY KEY,
    text          TEXT NOT NULL,              -- normalized English claim
    text_original TEXT,                       -- source-language wording
    lang          VARCHAR(8),
    embedding     VECTOR(384) NOT NULL,       -- sole cache key (multilingual-e5-small)
    first_seen    TIMESTAMPTZ DEFAULT NOW(),
    check_count   INT DEFAULT 1
);
CREATE INDEX ON claims USING hnsw (embedding vector_cosine_ops);

CREATE TABLE verdicts (
    id            BIGSERIAL PRIMARY KEY,
    claim_id      BIGINT REFERENCES claims(id) ON DELETE CASCADE,
    label         VARCHAR(16) NOT NULL
                  CHECK (label IN ('genuine','misleading','fake',
                                   'manipulated','insufficient')),
    confidence    REAL NOT NULL,
    explanation   TEXT,                       -- nullable: written after verdict (constraint #14)
    earliest_url  TEXT,                       -- reverse image search, image path only
    earliest_date TIMESTAMPTZ,               -- drives the manipulated label
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON verdicts (claim_id, expires_at DESC);

CREATE TABLE evidence (
    id           BIGSERIAL PRIMARY KEY,
    verdict_id   BIGINT REFERENCES verdicts(id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    domain       VARCHAR(255),
    title        TEXT,
    snippet      TEXT,
    stance       VARCHAR(16) CHECK (stance IN ('supports','refutes','neutral')),
    stance_score REAL,
    published_at TIMESTAMPTZ
);

CREATE TABLE sources (
    domain            VARCHAR(255) PRIMARY KEY,
    credibility_score REAL NOT NULL,
    category          VARCHAR(32),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
