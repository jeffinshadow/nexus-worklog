-- Ícone do projeto (Projetos v2, 01/11/2026): o nome de um ícone da biblioteca fixa do app
-- (app/schemas.py PROJECT_ICONS; validado no backend). NULL = pasta, o padrão.
-- Aditiva e idempotente: nada muda nos projetos que já existem.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS icon TEXT;
