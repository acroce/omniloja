SELECT
       b.est02_data AS data,
       r.ctb03_requisicao_id AS requisicao,
       sr.dom30_descricao AS status_requisicao,
       nf.fis01_nronf AS numero_nota,
       nf.fis01_serienf AS serie_nota,
       q.cfg06_numero AS loja,
       i.mcd01_codint AS produto,
       i.mcd01_descricao_curta AS descri,
       b.est02_qtd AS qtde,
       r.ctb04_custo_medio AS custo_medio,
       r.ctb04_custo_ultnf AS ultimo_custo,
       b.est02_qtd * r.ctb04_custo_medio AS total_custo_medio,
       b.est02_qtd * r.ctb04_custo_ultnf AS total_ultimo_custo
FROM est02_boletim_consumo_producao b
LEFT JOIN ctb04_requisicao_item r
       ON r.ctb04_id = b.ctb04_requisicao_item_id
LEFT JOIN ctb03_requisicao req
       ON req.ctb03_id = r.ctb03_requisicao_id
LEFT JOIN dom30_situacao_requisicao sr
       ON sr.dom30_id = req.dom30_situacao_requisicao_id
LEFT JOIN fis02_notafiscal_item nfi
       ON nfi.fis02_id = r.fis02_notafiscal_item_id
LEFT JOIN fis01_notafiscal nf
       ON nf.fis01_id = nfi.fis01_notafiscal_id
LEFT JOIN mcd03_mercadoria_filial g
       ON b.mcd03_mercadoria_filial_id = g.mcd03_id
LEFT JOIN mcd01_mercadoria i
       ON i.mcd01_id = g.mcd01_mercadoria_id
LEFT JOIN cfg06_filial q
       ON q.cfg06_id = g.cfg06_filial_id
WHERE b.est02_data >= %(start)s
  AND b.est02_data <= %(end)s
  AND b.dom18_finalidadenf_id = 3;
