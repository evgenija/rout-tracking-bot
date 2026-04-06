-- Міграція P1 DB: додати поле driver_type до таблиці drivers
-- Виконується ВРУЧНУ через Railway або psql. P1 код не чіпати.
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS driver_type VARCHAR(20) DEFAULT 'own';
-- Значення: 'logistics' | 'own'
