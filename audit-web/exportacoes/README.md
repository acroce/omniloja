# NOC — Rotina de exportação

Página `/exportacoes`, login `/exportacoes/login`, link no Monitor Operacional.

Cinco consultas fixas do Pleno: Exportação de vendas, Integração de Vendas,
Relatório de Retiradas, Encerramento de Caixa e Autoconsumo. Regras, ordem e cabeçalhos das
consultas fornecidas foram preservados. Datas são parâmetros enviados ao driver;
não existe execução de SQL recebido do navegador.

Período inicial: primeiro dia do mês até hoje. Datas inclusivas, máximo de 366 dias.
Nome do arquivo: `Nome do relatório_dd-mm_dd-mm.csv`, conforme solicitado.
CSV com BOM UTF-8, separador ponto e vírgula, decimais com vírgula e escape de
aspas/quebras de linha. Campos textuais que poderiam virar fórmulas no Excel são
prefixados por apóstrofo. Valores numéricos negativos são preservados.

## Acesso

Usuários persistidos em `outputs/noc_exportacoes_auth/users.json`, fora da pasta
pública, com hashes scrypt e salt individual. Criar usuário pelo administrador:

```sh
node audit-web/exportacoes/create-user.mjs nome_do_usuario
```

O comando gera uma senha aleatória, a exibe uma vez e não substitui usuários
existentes. Execute em terminal privado ou redirecione para arquivo modo 0600.
O arquivo de hashes precisa persistir no volume outputs. Para revogar um usuário,
remova sua entrada com o serviço parado e reinicie; sessões ficam em memória e
são encerradas no reinício. Não há autocadastro público.

Sessão de 8 horas, cookie HttpOnly/Secure/SameSite=Strict, token CSRF, limitação
de tentativas de login e downloads vinculados à sessão. O modo normal requer
HTTPS. `NOC_EXPORT_INSECURE_LOCAL=1` existe somente para teste local em loopback;
não usar em produção. `NOC_EXPORT_AUTH_DIR` permite trocar o diretório de hashes.

## Execução

O handler é integrado ao servidor NOC antes das rotas e arquivos estáticos.
Cada exportação usa um processo Python com PyMySQL já presente no NOC.
Credenciais são lidas do `.env` central montado em `/app/.env` e ambiente;
nenhuma cópia de credenciais do Pleno é criada. Opcional `NOC_EXPORT_ENV_FILE`.

A consulta executa em transação READ ONLY; timeout MySQL 120 segundos, processo
150 segundos, limite de arquivo 500 MiB. Uma exportação por vez evita sobrecarga.
CSV gerado em arquivo privado temporário, lido em lotes de 1000 linhas. Apenas
arquivos concluídos ficam disponíveis. Jobs são consultados por polling para
não depender do timeout do proxy. Arquivos expiram 15 minutos após o início.
Reiniciar o NOC cancela sessões/jobs; o usuário deve exportar novamente.
Logs contêm usuário, relatório, datas e quantidade, sem senha ou conteúdo do CSV.

API: `/api/noc-exportacoes/login`, `/session`, `/logout`, `/jobs`,
`/jobs/:id` e `/jobs/:id/download`. Relatórios e downloads exigem autenticação;
POST autenticado exige `X-CSRF-Token` retornado por `/session`.

## Conferência de negócio pendente

A consulta original de vendas soma valores de abertura/encerramento depois de
juntar `fcx22_encerramento_item`. Se houver vários itens para o mesmo
encerramento, venda, recebimentos e troco da base FCX podem se repetir. A base TES
tem prioridade quando existe. A implementação mantém a regra enviada pelo
solicitante; corrigir a agregação exige conferir o resultado de negócio esperado.

## Validação

`node --test audit-web/exportacoes/test.mjs` valida datas, nomes, autenticação,
CSRF, cookies, download, isolamento entre sessões, concorrência, falhas,
revogação por logout e bloqueio de tentativas. A evidência da publicação contém
os testes reais das quatro consultas, screenshots e validação HTTPS.
