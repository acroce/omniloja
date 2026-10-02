# Deploy Linux - Monitor NOC Pleno

## Subir o monitor

```sh
PACOTE="$(ls -1t noc-pleno-linux-*.tar.gz | head -1)"
tar -xzf "$PACOTE"
cd tabelas-pleno-vamos-criar-uma-conex
sh scripts/install_sap_api_monitor_linux_docker.sh
```

Se o Linux pedir permissao do Docker, o script vai relancar com `sudo`.
Se preferir rodar direto:

```sh
sudo sh scripts/install_sap_api_monitor_linux_docker.sh
```

No Linux este pacote usa, por padrao:

- container: `noc-pleno-audit-web`
- projeto Docker Compose: `noc-pleno`
- porta externa: `8095`

Ele nao deve usar/substituir o container antigo `pleno-audit-web`.

Para gerar um novo pacote no Mac:

```sh
sh scripts/build_noc_pleno_linux_package.sh
```

## Acesso

```text
http://IP_DA_MAQUINA:8095/
```

## Coletas automaticas

- APIs SAP: a cada 10 minutos, via SSH usando `config/pleno_fetch_remote.env`.
- Notas/check-in: a cada 10 minutos, usando o MySQL configurado no `.env`.
- Pedidos: janelas 07:50, 08:10 e 09:30.
- Promocao e precos: janelas 04:30 e 06:30.
- Estoque RELEX: 10:45, validando o arquivo do dia anterior.
- Retificacao RET: de hora em hora, alerta quando `RETIFICACAO_RET_*.*` passar de 3 arquivos.
- Recursos dos processos: a cada 5 minutos entre 04:00 e 09:59.

## Arquivos principais

- `docker-compose.audit.yml`: compose base.
- `docker-compose.audit-linux.yml`: override para Linux, `.env` e configs dentro do container.
- `scripts/update_sap_api_monitor.py`: coleta logs SAP.
- `scripts/update_checkin_notas_monitor.py`: coleta notas CD 704/check-in.
- `scripts/install_noc_monitoring_linux_cron.sh`: instala a crontab Linux chamando `docker exec noc-pleno-audit-web`.
- `scripts/update_retificacao_ret_monitor.py`: monitora `RETIFICACAO_RET_*.*`.
- `audit-web/public/sap-api-monitor.html`: tela do monitor.
