-- 003: Seed the sources table with credibility scores (PRD §9)
--
-- IFCN-signatory Indian fact-checkers: 0.90
-- Established wire services and national dailies: 0.75–0.85
-- Known low-credibility domains: 0.10
-- Default for unrated domains: 0.40 (handled in code, not seeded)

-- ══════════════════════════════════════════════════════════
-- IFCN-Signatory Indian Fact-Checkers (0.90)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('altnews.in',           0.90, 'fact_checker'),
('boomlive.in',          0.90, 'fact_checker'),
('factly.in',            0.90, 'fact_checker'),
('vishvasnews.com',      0.90, 'fact_checker'),
('newschecker.in',       0.90, 'fact_checker'),
('thequint.com',         0.88, 'fact_checker'),
('factcrescendo.com',    0.88, 'fact_checker'),
('digiteye.in',          0.85, 'fact_checker'),
('smhoaxslayer.com',     0.85, 'fact_checker'),
('logicallyfacts.com',   0.88, 'fact_checker');

-- ══════════════════════════════════════════════════════════
-- International Fact-Checkers (0.88–0.92)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('snopes.com',           0.92, 'fact_checker'),
('factcheck.org',        0.92, 'fact_checker'),
('politifact.com',       0.90, 'fact_checker'),
('fullfact.org',         0.90, 'fact_checker'),
('africacheck.org',      0.88, 'fact_checker'),
('chequeado.com',        0.88, 'fact_checker');

-- ══════════════════════════════════════════════════════════
-- Wire Services (0.85)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('reuters.com',          0.85, 'wire_service'),
('apnews.com',           0.85, 'wire_service'),
('afp.com',              0.85, 'wire_service'),
('pti.in',               0.82, 'wire_service'),
('ani.in',               0.78, 'wire_service');

-- ══════════════════════════════════════════════════════════
-- Major Indian National Dailies & Broadcasters (0.75–0.82)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('thehindu.com',         0.82, 'newspaper'),
('indianexpress.com',    0.82, 'newspaper'),
('hindustantimes.com',   0.78, 'newspaper'),
('timesofindia.indiatimes.com', 0.75, 'newspaper'),
('ndtv.com',             0.78, 'broadcaster'),
('bbc.com',              0.82, 'broadcaster'),
('bbc.co.uk',            0.82, 'broadcaster'),
('scroll.in',            0.78, 'digital_news'),
('thewire.in',           0.75, 'digital_news'),
('livemint.com',         0.75, 'newspaper'),
('deccanherald.com',     0.75, 'newspaper'),
('telegraphindia.com',   0.75, 'newspaper'),
('theprint.in',          0.75, 'digital_news');

-- ══════════════════════════════════════════════════════════
-- Major International Outlets (0.78–0.85)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('nytimes.com',          0.85, 'newspaper'),
('washingtonpost.com',   0.82, 'newspaper'),
('theguardian.com',      0.82, 'newspaper'),
('aljazeera.com',        0.78, 'broadcaster'),
('cnn.com',              0.75, 'broadcaster'),
('dw.com',               0.78, 'broadcaster');

-- ══════════════════════════════════════════════════════════
-- Regional Indian Language Outlets (0.70–0.78)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('dainikbhaskar.com',    0.70, 'newspaper'),
('amarujala.com',        0.70, 'newspaper'),
('jagran.com',           0.70, 'newspaper'),
('dinamalar.com',        0.70, 'newspaper'),
('anandabazar.com',      0.70, 'newspaper'),
('mathrubhumi.com',      0.72, 'newspaper'),
('manoramaonline.com',   0.72, 'newspaper'),
('esakal.com',           0.70, 'newspaper');

-- ══════════════════════════════════════════════════════════
-- Known Low-Credibility Domains (0.10)
-- ══════════════════════════════════════════════════════════
INSERT INTO sources (domain, credibility_score, category) VALUES
('opindia.com',          0.10, 'low_credibility'),
('swarajyamag.com',      0.20, 'low_credibility'),
('postcard.news',        0.10, 'low_credibility'),
('thelallantop.com',     0.35, 'entertainment'),
('kreately.in',          0.10, 'low_credibility');

-- Total: ~60 rows
