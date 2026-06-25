DROP TABLE IF EXISTS profile;

CREATE TABLE profile (
    id INT PRIMARY KEY,
    name TEXT,
    email TEXT,
    tier TEXT
);

INSERT INTO profile (id, name, email, tier) VALUES
    (1, 'Alice Adams',   'alice@traceflix.test', 'PREMIUM'),
    (2, 'Bob Brown',     'bob@traceflix.test',   'STANDARD'),
    (3, 'Carol Clark',   'carol@traceflix.test', 'PREMIUM'),
    (4, 'Dave Davis',    'dave@traceflix.test',  'BASIC'),
    (5, 'Erin Edwards',  'erin@traceflix.test',  'STANDARD');
