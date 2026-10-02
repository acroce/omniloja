# Robo de Transacao/Transferencia no Pleno

Este robo abre o Chrome com o perfil persistente do Pleno, usa as credenciais ja
configuradas no `.env`, acessa a tela:

```text
https://172.22.20.101/transacao-transferencia
```

Nesta primeira etapa ele apenas para na pagina e salva uma evidencia em:

```text
outputs/pleno-transacao-transferencia/pagina-transacao-transferencia.png
```

## Configuracao

Usa as mesmas variaveis do robo de check-in:

```dotenv
PLENO_USER=seu_usuario
PLENO_PASSWORD=sua_senha
PLENO_URL=https://172.22.20.101/Index
PLENO_TRANSFERENCIA_URL=https://172.22.20.101/transacao-transferencia
PLENO_TRANSFERENCIA_KEEP_OPEN=true
PLENO_TIMEOUT_MS=120000
PLENO_NAVIGATION_TIMEOUT_MS=120000
```

Se o Chrome estiver em outro caminho:

```dotenv
PLENO_CHROME_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

## Execucao

```bash
bash scripts/run-pleno-transacao-transferencia.sh
```

Ou:

```bash
npm run pleno-transacao-transferencia
```
