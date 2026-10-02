SELECT a.fcx07_id, f.cfg06_numero AS Filial, f.cfg06_nome AS Nome_filial,
 DATE_FORMAT(a.fcx07_data, '%%d/%%m/%%Y') AS Data, a.fcx07_pdv AS PDV,
 IFNULL(v.total_venda, 0) AS total_venda,
 IFNULL(ecf.venda_ecf_liquida, 0) AS venda_ecf_liquida,
 IFNULL(ecf.venda_ecf_bruta, 0) AS venda_ecf_bruta,
 IFNULL(v.total_venda, 0) - IFNULL(ecf.venda_ecf_liquida, 0) AS Diferenca
FROM (
 SELECT cfg06_filial_id, fcx07_data, fcx07_pdv, MIN(fcx07_id) AS fcx07_id
 FROM fcx07_abertura WHERE fcx07_data BETWEEN %(start)s AND %(end)s
 GROUP BY cfg06_filial_id, fcx07_data, fcx07_pdv
) a
INNER JOIN cfg06_filial f ON f.cfg06_id = a.cfg06_filial_id
LEFT JOIN (
 SELECT c.cfg06_filial_id, c.fcx01_data, c.fcx01_pdv, SUM(c.fcx01_vlrtotal) AS total_venda
 FROM fcx01_cupom c WHERE c.fcx01_data BETWEEN %(start)s AND %(end)s
 AND IFNULL(c.fcx01_cupom_id_cancelado, 0) = 0 AND IFNULL(c.fcx01_flgestornado, 0) = 0
 GROUP BY c.cfg06_filial_id, c.fcx01_data, c.fcx01_pdv
) v ON v.cfg06_filial_id = a.cfg06_filial_id AND v.fcx01_data = a.fcx07_data AND v.fcx01_pdv = a.fcx07_pdv
LEFT JOIN (
 SELECT ecf.cfg06_filial_id, ecf.fcx10_pdv, ve.fcx11_data,
 SUM(ve.fcx11_vlrvenda_liquida) AS venda_ecf_liquida, SUM(ve.fcx11_vlrvenda_bruta) AS venda_ecf_bruta
 FROM fcx11_venda_ecf ve INNER JOIN fcx10_ecf ecf ON ecf.fcx10_id = ve.fcx10_ecf_id
 WHERE ve.fcx11_data BETWEEN %(start)s AND %(end)s
 GROUP BY ecf.cfg06_filial_id, ecf.fcx10_pdv, ve.fcx11_data
) ecf ON ecf.cfg06_filial_id = a.cfg06_filial_id AND ecf.fcx10_pdv = a.fcx07_pdv AND ecf.fcx11_data = a.fcx07_data
WHERE a.fcx07_data BETWEEN %(start)s AND %(end)s
ORDER BY f.cfg06_numero, a.fcx07_data, a.fcx07_pdv
