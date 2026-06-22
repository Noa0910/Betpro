-- BetPro — esquema SQLite (referencia para migración futura a PostgreSQL/MySQL)
-- Motor actual: SQLite 3 (gratis, sin servidor)

-- USUARIOS (admin y clientes)
-- role: 'admin' | 'worker'

-- daily_reports.status: 'draft' | 'submitted' | 'confirmed'

-- Relaciones:
-- users 1──N daily_reports 1──N cargues | retiros | discounts
