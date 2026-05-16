-- ══════════════════════════════════════════
-- Store Manager — Supabase Schema
-- הרץ את זה ב-SQL Editor של Supabase
-- ══════════════════════════════════════════

-- טבלת הערות חנויות
CREATE TABLE IF NOT EXISTS store_notes (
    id         BIGSERIAL PRIMARY KEY,
    date       TEXT NOT NULL,
    store      TEXT NOT NULL,
    city       TEXT DEFAULT '',
    note       TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- טבלת ביקורים ידניים
CREATE TABLE IF NOT EXISTS manual_visits (
    id         BIGSERIAL PRIMARY KEY,
    date       TEXT NOT NULL,
    store      TEXT NOT NULL,
    city       TEXT DEFAULT '',
    status     TEXT DEFAULT 'ביקור',
    notes      TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- אינדקסים לביצועים
CREATE INDEX IF NOT EXISTS idx_notes_store   ON store_notes  (store);
CREATE INDEX IF NOT EXISTS idx_notes_date    ON store_notes  (date);
CREATE INDEX IF NOT EXISTS idx_visits_store  ON manual_visits(store);
CREATE INDEX IF NOT EXISTS idx_visits_date   ON manual_visits(date);

-- Row Level Security — פתוח לקריאה/כתיבה (אפליקציה פנימית)
ALTER TABLE store_notes   ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_visits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "allow_all_notes"  ON store_notes   FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_visits" ON manual_visits FOR ALL USING (true) WITH CHECK (true);
