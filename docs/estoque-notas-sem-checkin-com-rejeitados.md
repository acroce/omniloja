# Estoque com NFs Pendentes e Rejeitados

Esta rotina soma ao estoque novo do Pleno dois grupos, sempre por `loja + codigo do produto`:

- transferencias do CD 704 sem check-in no periodo informado;
- itens rejeitados do CSV consolidado, usando `qtd_xml_total`.

Os rejeitados preparados para a execucao de 11/08 estao em:

```text
outputs/rejeitados_lojas_proprias/itens_para_recriar_estoque_por_filial_20260811_223250/itens_para_recriar_estoque_consolidado_por_loja_artigo.csv
```

Depois de gerar o estoque novo, execute a soma assim:

```bash
python3 scripts/somar_estoque_com_notas_sem_checkin.py \
  --estoque CAMINHO_DO_ESTOQUE_NOVO.csv \
  --start-date 2026-08-01 \
  --end-date 2026-08-11 \
  --rejeitados-consolidado outputs/rejeitados_lojas_proprias/itens_para_recriar_estoque_por_filial_20260811_223250/itens_para_recriar_estoque_consolidado_por_loja_artigo.csv \
  --out-dir outputs/estoque_atual_mais_notas_sem_checkin_e_rejeitados_20260801_11 \
  --preserve-layout \
  --verify
```

O CSV final preserva o layout do estoque. Produtos que existem somente em NFs ou rejeitados, mas nao existem no estoque base, continuam fora do CSV final. A conferencia valida `estoque original + NFs pendentes + qtd_xml_total dos rejeitados`.
