-- Gauntlet R1: contato de suporte mostrado em "Ajuda" (texto livre: e-mail,
-- telefone, ramal ou link), configurável pelo admin. Aditivo e idempotente.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS support_contact TEXT
    CHECK (support_contact IS NULL OR char_length(support_contact) <= 200);
