DROP TABLE IF EXISTS title;

CREATE TABLE title (
    id INT PRIMARY KEY,
    name TEXT,
    genre TEXT,
    release_year INT,
    rating DOUBLE PRECISION
);

INSERT INTO title (id, name, genre, release_year, rating) VALUES
    (1,  'The Shawshank Redemption', 'Drama',    1994, 9.3),
    (2,  'The Godfather',            'Crime',    1972, 9.2),
    (3,  'The Dark Knight',          'Action',   2008, 9.0),
    (4,  'Pulp Fiction',             'Crime',    1994, 8.9),
    (5,  'Forrest Gump',             'Drama',    1994, 8.8),
    (6,  'Inception',                'Sci-Fi',   2010, 8.8),
    (7,  'Fight Club',               'Drama',    1999, 8.8),
    (8,  'The Matrix',               'Sci-Fi',   1999, 8.7),
    (9,  'Gladiator',                'Action',   2000, 8.5),
    (10, 'Saving Private Ryan',      'War',      1998, 8.6),
    (11, 'Interstellar',             'Sci-Fi',   2014, 8.7),
    (12, 'The Departed',             'Crime',    2006, 8.5);
