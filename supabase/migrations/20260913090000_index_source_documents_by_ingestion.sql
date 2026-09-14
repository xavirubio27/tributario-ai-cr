-- ============================================================================
-- Orden de llegada de la evidencia, indexado
--
-- POR QUE (fase C3, subfase B3-B). La bandeja de documentos responde a una
-- pregunta operativa -- "que ha recibido Tribuu y en que orden" -- y por tanto
-- ordena por LLEGADA, no por fecha de emision.
--
-- Los indices existentes no la sirven:
--
--     edoc_company_issued_idx      (company_id, issued_at DESC)
--         ordena por fecha del comprobante, no por cuando llego
--     sdoc_company_status_idx      (company_id, parse_status)
--         WHERE parse_status <> 'parsed'  -- PARCIAL: excluye lo procesado
--     sdoc_company_edoc_idx        (company_id, electronic_document_id)
--     sdoc_company_hash_idx        (company_id, content_sha256)
--
-- Y el identificador no sustituye al tiempo: `id` es `gen_random_uuid()`, sin
-- orden temporal, asi que no sirve de desempate ordenable por si solo.
--
-- `id DESC` acompana a `ingested_at DESC` porque la paginacion es por KEYSET y
-- necesita un orden TOTAL: dos artefactos pueden compartir milisegundo, y sin
-- desempate estable una pagina podria repetir o saltarse filas.
--
-- Solo un indice. Ni columnas, ni tablas, ni cambios de RLS: el estado durable
-- que ya escribe C2 basta para derivar la taxonomia operativa.
-- ============================================================================

create index if not exists sdoc_company_ingested_idx
    on fiscal.source_documents (company_id, ingested_at desc, id desc);
