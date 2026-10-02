WITH RECURSIVE parametros AS (
 SELECT DATE(%(start)s) AS data_inicial, DATE(%(end)s) AS data_final
), calendario AS (
 SELECT data_inicial AS data_movimento FROM parametros
 UNION ALL
 SELECT DATE_ADD(c.data_movimento, INTERVAL 1 DAY)
 FROM calendario c INNER JOIN parametros p ON c.data_movimento < p.data_final
), lojas AS (
 SELECT cfg06_id, cfg06_numero AS codigo_loja, cfg06_nome AS descricao_loja FROM cfg06_filial
), base_fcx AS (
 SELECT f.cfg06_numero AS codigo_loja, a.fcx07_data AS data_movimento,
 ROUND(SUM(IFNULL(e.fcx20_vlrvenda_liquida, 0)), 2) AS venda,
 ROUND(SUM(IFNULL(e.fcx20_vlrtotrecebto, 0)), 2) AS recebimentos,
 ROUND(SUM(IFNULL(a.fcx07_vlrdinheiro_inicial, 0)), 2) AS troco_inicial,
 ROUND(SUM(IFNULL(i.fcx22_valor, 0) + IFNULL(i.fcx22_valor_residuo, 0)), 2) AS m_pagtos,
 MIN(IFNULL(e.fcx20_flgfinalizado, 0)) AS flg_finalizado,
 COUNT(DISTINCT e.fcx20_id) AS qtd_encerramentos
 FROM fcx07_abertura a
 INNER JOIN cfg06_filial f ON f.cfg06_id = a.cfg06_filial_id
 LEFT JOIN fcx20_encerramento e ON e.fcx07_abertura_id = a.fcx07_id
 LEFT JOIN fcx22_encerramento_item i ON i.fcx20_encerramento_id = e.fcx20_id
 CROSS JOIN parametros p
 WHERE a.fcx07_data BETWEEN p.data_inicial AND p.data_final
 GROUP BY f.cfg06_numero, a.fcx07_data
), base_tes AS (
 SELECT f.cfg06_numero AS codigo_loja, p.tes01_data AS data_movimento,
 ROUND(IFNULL(p.tes01_vlrvenda_liquida, 0), 2) AS venda,
 ROUND(IFNULL(p.tes01_vlrtotrecebto, 0), 2) AS recebimentos,
 ROUND(IFNULL(p.tes01_vlrtroco, 0), 2) AS troco_inicial,
 ROUND(IFNULL(p.tes01_vlrtotmpagto, 0), 2) AS m_pagtos,
 IFNULL(p.tes01_flgfechada, 0) AS flg_fechada,
 IFNULL(p.tes01_flgexportada, 0) AS flg_exportada,
 p.tes01_id AS id_prestacao
 FROM tes01_prestacao p INNER JOIN cfg06_filial f ON f.cfg06_id = p.cfg06_filial_id
 CROSS JOIN parametros par WHERE p.tes01_data BETWEEN par.data_inicial AND par.data_final
)
SELECT l.codigo_loja AS `CodigoLoja`, l.descricao_loja AS `DescricaoLoja`, c.data_movimento AS `Data`,
 COALESCE(tes.venda, fcx.venda, 0) AS `Venda`,
 COALESCE(tes.recebimentos, fcx.recebimentos, 0) AS `Recebimentos`,
 ROUND(COALESCE(tes.venda, fcx.venda, 0) + COALESCE(tes.recebimentos, fcx.recebimentos, 0) + COALESCE(tes.troco_inicial, fcx.troco_inicial, 0), 2) AS `Total`,
 COALESCE(tes.troco_inicial, fcx.troco_inicial, 0) AS `TrocoInicial`,
 COALESCE(tes.m_pagtos, fcx.m_pagtos, 0) AS `M.Pagtos`,
 ROUND(COALESCE(tes.m_pagtos, fcx.m_pagtos, 0) - (COALESCE(tes.venda, fcx.venda, 0) + COALESCE(tes.recebimentos, fcx.recebimentos, 0) + COALESCE(tes.troco_inicial, fcx.troco_inicial, 0)), 2) AS `Diferenca`,
 CASE
 WHEN IFNULL(fcx.qtd_encerramentos, 0) = 0 AND tes.id_prestacao IS NULL THEN 'Aguardando'
 WHEN tes.id_prestacao IS NULL THEN 'Aguardando'
 WHEN tes.flg_fechada = 0 THEN 'Aberta'
 WHEN tes.flg_fechada = 1 AND tes.flg_exportada = 1 THEN 'Exportada'
 WHEN tes.flg_fechada = 1 AND tes.flg_exportada = 0 THEN 'Analise'
 ELSE 'Aberta' END AS `Situacao`,
 CASE WHEN tes.id_prestacao IS NOT NULL AND tes.flg_exportada = 0 THEN 'Reimportar' ELSE '' END AS `Reimportar`
FROM calendario c CROSS JOIN lojas l
LEFT JOIN base_fcx fcx ON fcx.codigo_loja = l.codigo_loja AND fcx.data_movimento = c.data_movimento
LEFT JOIN base_tes tes ON tes.codigo_loja = l.codigo_loja AND tes.data_movimento = c.data_movimento
ORDER BY c.data_movimento DESC, l.codigo_loja
