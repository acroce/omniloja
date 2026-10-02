SELECT f.cfg06_numero AS Filial, f.cfg06_nome AS nome_filial, a.fcx07_pdv AS PDV,
 DATE_FORMAT(r.fcx18_data, '%%d/%%m/%%Y') AS Data, r.fcx18_hora AS Hora,
 op.adm05_codigo_fcx AS codigo_operador, r.adm05_usuario_id_operador,
 sup.adm05_codigo_fcx AS codigo_supervisor, r.adm05_usuario_id_supervisor,
 r.fcx18_nroretirada AS numero_retirada,
 mp.cfg09_codigo AS codigo_pagamento, mp.cfg09_descricao AS descricao_pagamento,
 ri.fcx19_valor AS valor_retirado_dinheiro
FROM fcx18_retirada r
INNER JOIN fcx07_abertura a ON a.fcx07_id = r.fcx07_abertura_id
INNER JOIN cfg06_filial f ON f.cfg06_id = a.cfg06_filial_id
INNER JOIN fcx19_retirada_item ri ON ri.fcx18_retirada_id = r.fcx18_id
INNER JOIN cfg09_mpagto mp ON mp.cfg09_id = ri.cfg09_mpagto_id
LEFT JOIN adm05_usuario op ON op.adm05_id = r.adm05_usuario_id_operador
LEFT JOIN adm05_usuario sup ON sup.adm05_id = r.adm05_usuario_id_supervisor
WHERE r.fcx18_data BETWEEN %(start)s AND %(end)s AND mp.cfg09_codigo = 1
ORDER BY f.cfg06_numero, r.fcx18_data, a.fcx07_pdv, r.fcx18_nroretirada
