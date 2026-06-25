DROP TABLE IF EXISTS account;

CREATE TABLE account (
    id INT PRIMARY KEY,
    username TEXT,
    role TEXT,
    token TEXT
);

INSERT INTO account (id, username, role, token) VALUES
    (1, 'alice',   'PREMIUM',  'tok-alice'),
    (2, 'bob',     'STANDARD', 'tok-bob'),
    (3, 'carol',   'PREMIUM',  'tok-carol'),
    (4, 'dave',    'BASIC',    'tok-dave'),
    (5, 'erin',    'STANDARD', 'tok-erin');
