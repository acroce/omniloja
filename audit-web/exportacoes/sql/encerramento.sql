SELECT f.cfg06_numero AS Filial, f.cfg06_nome AS Nome,
 DATE_FORMAT(a.fcx07_data, '%%d/%%m/%%Y') AS Data,
 a.fcx07_numabertura AS Abertura, a.fcx07_pdv AS PDV,
 CONCAT(IFNULL(op.adm05_codigo_fcx, ''), ' / ', IFNULL(sup.adm05_codigo_fcx, '')) AS Operadores,
 e.fcx20_vlrvenda_liquida AS valor_liquido, e.fcx20_vlrtotrecebto AS Recebimentos,
 e.fcx20_vlrvenda_liquida + e.fcx20_vlrtotrecebto AS Total,
 e.fcx20_vlrtotmpagto AS total_mpagto,
 IFNULL(mp.valor_residuo, 0) AS residuo_mpagto,
 IFNULL(ret.total_retiradas, 0) AS total_retiradas,
 IFNULL(ret.total_retiradas, 0) - e.fcx20_vlrtotmpagto AS diferenca,
 CASE WHEN e.fcx20_flgfinalizado = 1 THEN 'Finalizado' ELSE 'Pendente' END AS Situacao,
 sup.adm05_usuario AS Supervisor
FROM fcx20_encerramento e
INNER JOIN fcx07_abertura a ON a.fcx07_id = e.fcx07_abertura_id
INNER JOIN cfg06_filial f ON f.cfg06_id = a.cfg06_filial_id
LEFT JOIN adm05_usuario op ON op.adm05_id = e.adm05_usuario_id_operador
LEFT JOIN adm05_usuario sup ON sup.adm05_id = e.adm05_usuario_id_supervisor
LEFT JOIN (
 SELECT fcx20_encerramento_id, SUM(fcx22_valor_residuo) AS valor_residuo
 FROM fcx22_encerramento_item GROUP BY fcx20_encerramento_id
) mp ON mp.fcx20_encerramento_id = e.fcx20_id
LEFT JOIN (
 SELECT r.fcx07_abertura_id, SUM(ri.fcx19_valor) AS total_retiradas
 FROM fcx18_retirada r INNER JOIN fcx19_retirada_item ri ON ri.fcx18_retirada_id = r.fcx18_id
 GROUP BY r.fcx07_abertura_id
) ret ON ret.fcx07_abertura_id = a.fcx07_id
WHERE a.fcx07_data BETWEEN %(start)s AND %(end)s
ORDER BY f.cfg06_numero, a.fcx07_data, a.fcx07_pdv, a.fcx07_numabertura
