# Copia dos fontes - Auditoria Pleno

Esta pasta e uma copia limpa dos fontes para iniciar um novo produto a partir da Auditoria Pleno.

## O que foi copiado

- Codigo da aplicacao web em `audit-web/`
- Scripts de coleta/processamento em `scripts/` e `cronbin/`
- Dockerfiles e `docker-compose*.yml`
- Documentacao em `docs/`
- Exemplos de configuracao em `config/*.example`
- Estruturas auxiliares de `src/`, `docker/`, `public/` e apps internos

## O que ficou fora de proposito

- `outputs/`, `tmp/`, `reports/`, `backups/`
- Ambientes virtuais e dependencias locais: `.venv/`, `.venv_devolucao/`, `.python_packages/`
- Perfis de navegador/cache: `.cache/`, `.google-chat-profile/`
- Credenciais e chaves: `.env`, symlinks de env, `.noc_pleno_deploy_ed25519*`
- Arquivos grandes ou de dados: `*.tar.gz`, `*.zip`, `estoque_*.csv`
- Arquivos locais sensiveis como `credential-inventory-local.txt`

## Para transformar em produto novo

1. Renomeie a pasta para o nome do produto.
2. Crie um novo `.env` a partir dos exemplos necessarios.
3. Revise `docker-compose*.yml` para nomes de containers, portas e volumes do novo produto.
4. Ajuste textos/rotas em `audit-web/public/index.html` e `audit-web/server.mjs`.
5. Gere dados novos no ambiente destino, sem reaproveitar `outputs` antigos.

