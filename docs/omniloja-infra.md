# Infra Omniloja

Infra paralela e isolada para rodar o Omniloja sem afetar os containers atuais.

## Containers

- `omniloja-nginx`: entrada HTTP e proxy reverso.
- `omniloja-web`: aplicacao Node/Python do Omniloja.
- `omniloja-db`: banco MySQL proprio do produto.

## Subir localmente

```bash
docker compose -p omniloja -f docker-compose.omniloja.yml up -d --build
```

A URL padrao fica em:

```text
http://localhost:8098
```

Para usar outra porta:

```bash
OMNILOJA_HTTP_PORT=8100 docker compose -p omniloja -f docker-compose.omniloja.yml up -d --build
```

## Verificar

```bash
docker compose -p omniloja -f docker-compose.omniloja.yml ps
docker compose -p omniloja -f docker-compose.omniloja.yml logs -f omniloja-web
curl -fsS http://localhost:8098/health
```

## Banco

O MySQL usa volume Docker proprio:

```text
omniloja-db-data
```

Credenciais padrao de desenvolvimento:

```text
OMNILOJA_DB_NAME=omniloja
OMNILOJA_DB_USER=omniloja
OMNILOJA_DB_PASSWORD=omniloja_dev_password
OMNILOJA_DB_ROOT_PASSWORD=omniloja_root_dev_password
```

Em servidor, configure esses valores no `.env` antes de subir.

## Conexao Pleno

Por padrao, o container web usa o banco local `omniloja-db`, bom para demo.
Para conectar em um Pleno externo, use variaveis especificas do Omniloja:

```text
OMNILOJA_PLENO_MYSQL_HOST=
OMNILOJA_PLENO_MYSQL_PORT=3306
OMNILOJA_PLENO_MYSQL_USER=
OMNILOJA_PLENO_MYSQL_PASSWORD=
OMNILOJA_PLENO_MYSQL_DATABASE=pleno
```

Sem essas variaveis, o app usa:

```text
MYSQL_HOST=omniloja-db
MYSQL_DATABASE=omniloja
```

## Seed demo

Para carregar um recorte anonimizado do banco antigo no banco local:

```bash
scripts/seed_omniloja_demo_db.sh
```

O script usa as lojas de `config/pleno_stock_audit_lojas.txt`, pega uma janela
recente de dados e troca referencias textuais a DIA/DIABRASIL por OMNILOJA.

## Parar

```bash
docker compose -p omniloja -f docker-compose.omniloja.yml down
```

Para remover tambem os volumes do Omniloja:

```bash
docker compose -p omniloja -f docker-compose.omniloja.yml down -v
```
