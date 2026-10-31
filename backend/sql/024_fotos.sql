-- Fotos na tarefa e como evidência da rotina (print do erro, foto do rack).
-- O navegador reduz (lado maior 1600 px), regrava em WebP/JPEG — o que apaga
-- EXIF e GPS — e manda junto a miniatura. Aditivo e idempotente.

-- Cota por pessoa (MB), definida pelo admin em Admin › Geral.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS photo_quota_mb INT NOT NULL DEFAULT 500
    CHECK (photo_quota_mb BETWEEN 0 AND 100000);

CREATE TABLE IF NOT EXISTS photos (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Sem FK na tarefa: excluir e desfazer devolve as fotos (a faxina leva as
    -- órfãs depois da janela do desfazer).
    task_id      BIGINT,
    recurring_id BIGINT REFERENCES recurring_tasks(id) ON DELETE CASCADE,
    day          DATE,
    mime         TEXT NOT NULL CHECK (mime IN ('image/webp', 'image/jpeg', 'image/png')),
    image        BYTEA NOT NULL,
    thumb        BYTEA NOT NULL,
    width        SMALLINT,
    height       SMALLINT,
    bytes        INT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ,   -- excluída: some na hora, volta pelo desfazer, sai de vez em 7 dias
    CHECK ((task_id IS NULL) <> (recurring_id IS NULL)),
    CHECK (recurring_id IS NULL OR day IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_photos_task ON photos(user_id, task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_photos_routine ON photos(user_id, recurring_id, day) WHERE recurring_id IS NOT NULL;
