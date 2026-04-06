-- Міграція P1 DB: додати поле driver_type до таблиці users
-- P1 використовує SQLite. Таблиця users (не drivers).
-- Виконується ВРУЧНУ через sqlite3 CLI або Railway shell. P1 код не чіпати.
ALTER TABLE users ADD COLUMN driver_type TEXT DEFAULT 'own';
-- Значення: 'logistics' | 'own'
-- Примітка: SQLite < 3.37 не підтримує IF NOT EXISTS для ALTER TABLE ADD COLUMN.
-- Якщо колонка вже є — команда поверне помилку, можна ігнорувати.
