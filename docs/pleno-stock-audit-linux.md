# Auditoria de estoque Pleno no Linux

Este pacote roda a aplicacao web da auditoria de estoque no Linux com Docker e busca diaria dos arquivos gerados nos servidores.

## Arquitetura

- Servidor coletor de movimentos: gera os `.tar.gz` em `/dev/audit_lojas/outputs/pleno_stock_audit_packages`.
- Servidor do estoque oficial: disponibiliza `estoque_YYYYMMDD*.csv`.
- Servidor Linux da auditoria: roda o Docker da tela, busca os arquivos todo dia as 09:00 e processa automaticamente a pasta `outputs/recebidos_servidor`.

## Instalar no Linux

```sh
tar -xzf pleno-stock-audit-linux-YYYYMMDD-HHMM.tar.gz
cd tabelas-pleno-vamos-criar-uma-conex
cp config/pleno_fetch_remote.env.example config/pleno_fetch_remote.env
vi config/pleno_fetch_remote.env
sh scripts/install_pleno_stock_audit_linux_docker.sh
```

A aplicacao sobe em:

```text
http://IP_DO_LINUX:8094
```

## Configurar servidores remotos

No `config/pleno_fetch_remote.env`, preencha:

```sh
PACKAGE_REMOTE_USER=usuario_movimentos
PACKAGE_REMOTE_HOST=ip_ou_dns_movimentos
PACKAGE_REMOTE_PORT=22
PACKAGE_REMOTE_PASSWORD="senha_movimentos"
PACKAGE_REMOTE_DIRS="/dev/audit_lojas/outputs/pleno_stock_audit_packages /dev/audit_lojas/outputs/pleno_stock_snapshot_packages"

STOCK_REMOTE_USER=usuario_estoque
STOCK_REMOTE_HOST=ip_ou_dns_estoque
STOCK_REMOTE_PORT=22
STOCK_REMOTE_PASSWORD="senha_estoque"
STOCK_REMOTE_DIRS="/dev/audit_lojas/outputs/pleno_stock_official /dev/audit_lojas/outputs/recebidos_servidor"
```

## Teste manual da busca

```sh
docker exec pleno-audit-web /app/scripts/fetch_pleno_audit_files_local.sh
```

Depois aguarde ate 10 minutos ou reinicie o container para forcar a varredura inicial:

```sh
docker restart pleno-audit-web
```

## Rotina automatica

O instalador cria uma crontab no Linux:

```text
0 9 * * * docker exec pleno-audit-web /app/scripts/fetch_pleno_audit_files_local.sh
```

Log:

```text
outputs/logs/pleno_stock_audit_fetch_linux.log
```

## Adicionar lojas

No servidor que gera os pacotes da auditoria, adicione as lojas no arquivo:

```text
/dev/audit_lojas/config/pleno_stock_audit_lojas.txt
```

Uma loja por linha:

```text
259
1174
1201
```

Se o helper estiver no servidor:

```sh
/dev/audit_lojas/scripts/add_pleno_stock_audit_lojas.sh 259 1174 1201
```

Os proximos pacotes diarios ja saem com as lojas novas. A tela do Linux separa os dados por loja automaticamente pelo seletor.

## Comandos uteis

Ver container:

```sh
docker ps | grep pleno-audit-web
```

Ver logs da aplicacao:

```sh
docker logs -f pleno-audit-web
```

Recriar indices de estoque oficial:

```sh
docker exec pleno-audit-web python3 /app/scripts/build_pleno_stock_official_index.py
```
