-- Esquema analítico de pocket price.
-- fact_venta = extracto del ERP (solo lo que SAP registra).
-- condiciones_extra_sap / topes_politica / excepciones_comite = lo que la
-- ingesta extrae de los documentos con un LLM (salida estructurada).
-- Montos en PEN y por línea.

CREATE TABLE IF NOT EXISTS dim_producto (
    sku            TEXT PRIMARY KEY,
    nombre         TEXT NOT NULL,
    categoria      TEXT NOT NULL,   -- grupo de productos
    unidad         TEXT NOT NULL,
    division       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_costo (
    sku            TEXT NOT NULL REFERENCES dim_producto,
    anio           INTEGER NOT NULL,
    costo_unitario NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (sku, anio)
);

CREATE TABLE IF NOT EXISTS dim_cliente (
    cliente_id     TEXT PRIMARY KEY,
    nombre         TEXT NOT NULL,
    canal          TEXT NOT NULL,
    region         TEXT NOT NULL,   -- macrorregión
    segmento       TEXT NOT NULL,
    tipo_venta     TEXT NOT NULL,
    gerencia       TEXT NOT NULL,
    ejecutivo      TEXT NOT NULL,
    departamento   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_venta (
    linea_id            BIGINT PRIMARY KEY,
    fecha               DATE NOT NULL,
    cliente_id          TEXT NOT NULL REFERENCES dim_cliente,
    sku                 TEXT NOT NULL REFERENCES dim_producto,
    cantidad            INTEGER NOT NULL,
    plazo_pago_dias     INTEGER NOT NULL,
    precio_lista_unit   NUMERIC(12,2) NOT NULL,
    dscto_comercial     NUMERIC(14,2) NOT NULL,
    dscto_volumen       NUMERIC(14,2) NOT NULL,
    dscto_pronto_pago   NUMERIC(14,2) NOT NULL,
    flete               NUMERIC(14,2) NOT NULL,
    costo_financiero    NUMERIC(14,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_venta_fecha   ON fact_venta (fecha);
CREATE INDEX IF NOT EXISTS ix_fact_venta_cliente ON fact_venta (cliente_id);

-- ---------------------------------------------------------------- extracción

CREATE TABLE IF NOT EXISTS condiciones_extra_sap (
    id                 TEXT PRIMARY KEY,
    tipo               TEXT NOT NULL CHECK (tipo IN ('grilla', 'campana', 'rebate')),
    documento_id       TEXT NOT NULL,
    cliente_id         TEXT,
    canal              TEXT,
    categoria          TEXT,
    cantidad_min       INTEGER,
    pct                NUMERIC(6,4),
    objetivo_unidades  INTEGER,
    tramos             JSONB,          -- [{"cumplimiento_min": 0.9, "pct": 0.02}, ...]
    vigencia_desde     DATE NOT NULL,
    vigencia_hasta     DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS topes_politica (
    documento_id    TEXT NOT NULL,
    canal           TEXT NOT NULL,
    tope_pct        NUMERIC(6,4) NOT NULL,
    vigencia_desde  DATE NOT NULL,
    vigencia_hasta  DATE NOT NULL,
    PRIMARY KEY (documento_id, canal)
);

CREATE TABLE IF NOT EXISTS excepciones_comite (
    documento_id    TEXT NOT NULL,
    cliente_id      TEXT NOT NULL,
    estado          TEXT NOT NULL CHECK (estado IN ('aprobada', 'rechazada')),
    concepto        TEXT NOT NULL,
    tope_pct        NUMERIC(6,4),
    vigencia_desde  DATE,
    vigencia_hasta  DATE,
    PRIMARY KEY (documento_id, cliente_id)
);

-- Bitácora de la extracción: evita reprocesar documentos sin cambios.
CREATE TABLE IF NOT EXISTS extraccion_log (
    documento_id   TEXT PRIMARY KEY,
    hash_archivo   TEXT NOT NULL,
    modelo         TEXT NOT NULL,
    filas          INTEGER NOT NULL,
    extraido_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Alertas que registra el agente (única escritura; requiere aprobación humana).
CREATE TABLE IF NOT EXISTS alertas_pricing (
    id               BIGSERIAL PRIMARY KEY,
    cliente_id       TEXT NOT NULL,   -- sin FK: init recarga dim_cliente con TRUNCATE
    motivo           TEXT NOT NULL,
    monto_estimado   NUMERIC(14,2),
    thread_id        TEXT,
    creada_en        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- vistas

-- Cascada con lo que registra SAP.
CREATE OR REPLACE VIEW v_cascada_sap AS
SELECT b.*,
       b.venta_lista - b.dscto_comercial - b.dscto_volumen                       AS venta_factura,
       b.venta_lista - b.dscto_comercial - b.dscto_volumen
         - b.dscto_pronto_pago - b.flete - b.costo_financiero                   AS venta_pocket_sap
FROM (
    SELECT f.*,
           p.nombre AS producto, p.categoria, p.division,
           c.nombre AS cliente, c.canal, c.region, c.segmento,
           c.tipo_venta, c.gerencia, c.ejecutivo, c.departamento,
           date_trunc('quarter', f.fecha)::date AS trimestre,
           f.precio_lista_unit * f.cantidad     AS venta_lista,
           co.costo_unitario * f.cantidad       AS costo_total
    FROM fact_venta f
    JOIN dim_producto p USING (sku)
    JOIN dim_cliente  c USING (cliente_id)
    JOIN dim_costo   co ON co.sku = f.sku AND co.anio = EXTRACT(YEAR FROM f.fecha)
) b;

-- Cascada real: suma los acuerdos fuera de SAP extraídos de los documentos.
CREATE OR REPLACE VIEW v_cascada_real AS
WITH vol AS (
    SELECT cliente_id, trimestre, SUM(cantidad) AS unidades
    FROM v_cascada_sap GROUP BY 1, 2
),
rebate AS (
    SELECT v.cliente_id, v.trimestre,
           (SELECT MAX((t ->> 'pct')::numeric)
              FROM jsonb_array_elements(c.tramos) t
             WHERE v.unidades::numeric / c.objetivo_unidades >= (t ->> 'cumplimiento_min')::numeric) AS pct
    FROM vol v
    JOIN condiciones_extra_sap c
      ON c.tipo = 'rebate' AND c.cliente_id = v.cliente_id
     AND v.trimestre BETWEEN c.vigencia_desde AND c.vigencia_hasta
),
x AS (
    SELECT s.*,
           COALESCE(g.pct, 0)  * s.venta_factura AS dscto_grilla,
           COALESCE(cp.pct, 0) * s.venta_factura AS dscto_campana,
           COALESCE(r.pct, 0)  * s.venta_factura AS rebate_carta
    FROM v_cascada_sap s
    LEFT JOIN LATERAL (
        SELECT SUM(pct) AS pct FROM condiciones_extra_sap c
        WHERE c.tipo = 'grilla' AND c.categoria = s.categoria AND c.canal = s.canal
          AND s.fecha BETWEEN c.vigencia_desde AND c.vigencia_hasta) g ON true
    LEFT JOIN LATERAL (
        SELECT SUM(pct) AS pct FROM condiciones_extra_sap c
        WHERE c.tipo = 'campana' AND c.canal = s.canal
          AND s.cantidad >= COALESCE(c.cantidad_min, 0)
          AND s.fecha BETWEEN c.vigencia_desde AND c.vigencia_hasta) cp ON true
    LEFT JOIN rebate r ON r.cliente_id = s.cliente_id AND r.trimestre = s.trimestre
)
SELECT x.*,
       x.venta_pocket_sap - x.dscto_grilla - x.dscto_campana - x.rebate_carta AS venta_pocket_real,
       x.venta_pocket_sap - x.costo_total                                     AS margen_sap,
       x.venta_pocket_sap - x.dscto_grilla - x.dscto_campana - x.rebate_carta
         - x.costo_total                                                      AS margen_real
FROM x;

-- Versión materializada de la cascada real: la vista recalcula grillas, campañas y
-- rebates por línea en cada consulta (~8 s); materializada responde en milisegundos.
-- La ingesta la refresca al terminar la extracción (REFRESH MATERIALIZED VIEW).
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_cascada_real AS SELECT * FROM v_cascada_real;
CREATE INDEX IF NOT EXISTS ix_mv_fecha     ON mv_cascada_real (fecha);
CREATE INDEX IF NOT EXISTS ix_mv_cliente   ON mv_cascada_real (cliente_id, fecha);
CREATE INDEX IF NOT EXISTS ix_mv_canal     ON mv_cascada_real (canal, fecha);
CREATE INDEX IF NOT EXISTS ix_mv_categoria ON mv_cascada_real (categoria, fecha);

-- ---------------------------------------------------------------- seguridad

-- El agente consulta con un usuario de SOLO LECTURA (OWASP LLM06):
-- aunque un prompt lograra alterar una consulta, la base no permite escribir.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agente_ro') THEN
        CREATE ROLE agente_ro LOGIN PASSWORD 'agente_ro';
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO agente_ro;
GRANT SELECT ON dim_producto, dim_costo, dim_cliente, fact_venta,
                condiciones_extra_sap, topes_politica, excepciones_comite,
                v_cascada_sap, v_cascada_real, mv_cascada_real TO agente_ro;
