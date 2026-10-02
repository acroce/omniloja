WITH pedidos AS (
    SELECT
        com16_id,
        cfg06_filial_dest_id,
        com16_nro_pedtransf_trd,
        com16_flgatendido_trd,
        com16_dthr
    FROM pleno.com16_pretransferencia
    WHERE com16_dthr >= CURDATE() - INTERVAL 7 DAY
      AND dom83_tipo_pedtransf_id = 3
),
status_pedido AS (
    SELECT
        a.com16_pretransferencia_id,
        MAX(f.fis01_nronf) AS nr_nota_pedido,
        MAX(e.fis02_notafiscal_item_id) AS item_nf_pedido
    FROM pedidos b
    INNER JOIN pleno.com19_pretransferencia_item a
        ON a.com16_pretransferencia_id = b.com16_id
    LEFT JOIN pleno.com33_pedtransf_atendido d
        ON d.com19_pretransferencia_item_id = a.com19_id
    LEFT JOIN pleno.fis25_notafiscal_item_fisico e
        ON e.fis25_id = d.fis25_notafiscal_item_fisico_id
    LEFT JOIN pleno.fis01_notafiscal f
        ON f.fis01_id = e.fis01_notafiscal_id
    GROUP BY
       a.com16_pretransferencia_id
),
detalhe AS (
    SELECT
       c.cfg06_numero AS Loja,
       c.cfg06_nome AS Nome_loja,
       b.com16_nro_pedtransf_trd AS Pedido,
       b.com16_flgatendido_trd AS Atendido,
       b.com16_dthr AS Dt_Pedido,
       g.mcd01_codint AS SKU,
       g.mcd01_descricao_curta AS Descri,
       a.com19_qtd AS qtde_ped,
       a.com19_qtd_confirmada AS qtde_conf_ped,
       e.fis25_qtd_nf AS qtde_nota,
       COALESCE(f.fis01_nronf, sp.nr_nota_pedido) AS nr_nota,
       COALESCE(e.fis02_notafiscal_item_id, sp.item_nf_pedido) AS fis02_notafiscal_item_id,
       CASE
           WHEN sp.item_nf_pedido IS NOT NULL THEN 'Entrada realizada'
           ELSE 'Pendente Entrada'
       END AS Situacao
    FROM pedidos b
    INNER JOIN pleno.com19_pretransferencia_item a
        ON a.com16_pretransferencia_id = b.com16_id
    INNER JOIN pleno.cfg06_filial c
        ON c.cfg06_id = b.cfg06_filial_dest_id
    LEFT JOIN pleno.com33_pedtransf_atendido d
        ON d.com19_pretransferencia_item_id = a.com19_id
    LEFT JOIN pleno.fis25_notafiscal_item_fisico e
        ON e.fis25_id = d.fis25_notafiscal_item_fisico_id
    LEFT JOIN pleno.fis01_notafiscal f
        ON f.fis01_id = e.fis01_notafiscal_id
    LEFT JOIN pleno.mcd01_mercadoria g
        ON g.mcd01_id = a.mcd01_mercadoria_id
    LEFT JOIN status_pedido sp
        ON sp.com16_pretransferencia_id = b.com16_id
    WHERE b.com16_dthr >= '2026-07-02'
)
SELECT
    Situacao,
    COUNT(*) AS linhas,
    COUNT(DISTINCT Pedido) AS pedidos,
    COALESCE(SUM(qtde_ped), 0) AS qtde_ped,
    COALESCE(SUM(qtde_nota), 0) AS qtde_nota
FROM detalhe
GROUP BY Situacao
ORDER BY Situacao;
