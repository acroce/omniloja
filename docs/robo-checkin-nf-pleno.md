# Robo de check-in de NF Transferencia no Pleno

Este robo entra no Pleno, abre a tela:

`Recebimento > Transferencia > NF Transf - Check-in`

URL direta:

`https://172.22.20.101/notafiscal-transf-checkin`

Depois ele preenche `chave nf*` e clica no botao `Checkin` para cada chave informada.

Para cada chave, o robo aguarda o retorno da tela. Assim que aparece uma resposta, ele classifica o resultado e ja segue para a proxima chave. Mensagens como `NF ja fechada`, `check-in ja realizado` ou equivalentes entram como OK, porque indicam que a nota ja esta com check-in resolvido.

## Arquivo de chaves

Preencha:

```text
data/pleno-checkin-chaves.txt
```

Formato recomendado:

```text
35260700000000000000550010000000000000000000
35260700000000000000550010000000000000000001
```

O robo tambem aceita CSV, desde que exista uma chave NF-e de 44 digitos na linha.

## Configuracao no `.env`

As credenciais ja usadas no login tambem servem aqui:

```dotenv
PLENO_USER=seu_usuario
PLENO_PASSWORD=sua_senha
PLENO_URL=https://172.22.20.101/Index
PLENO_CHECKIN_URL=https://172.22.20.101/notafiscal-transf-checkin
PLENO_TIMEOUT_MS=120000
PLENO_NAVIGATION_TIMEOUT_MS=120000
PLENO_CHECKIN_RESULT_TIMEOUT_MS=120000
PLENO_CHECKIN_READ_AFTER_CLICK_MS=0
PLENO_CHECKIN_MESSAGE_READ_DELAY_MS=0
PLENO_CHECKIN_RESULT_POLL_MS=200
PLENO_CHECKIN_USE_GENERIC_FEEDBACK=false
PLENO_CHECKIN_AFTER_RESULT_DELAY_MS=0
PLENO_CHECKIN_RELOAD_BETWEEN_KEYS=true
PLENO_CHECKIN_WORKERS=1
```

Se precisar usar outro arquivo:

```dotenv
PLENO_CHECKIN_KEYS_FILE=/caminho/para/chaves.txt
```

Se o Chrome estiver em outro caminho:

```dotenv
PLENO_CHROME_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

Se o robo nao encontrar os campos automaticamente, ajuste os seletores:

```dotenv
PLENO_CHECKIN_CHAVE_SELECTOR=#chaveNf
PLENO_CHECKIN_BUTTON_SELECTOR=#btnCheckin
```

## Execucao

```bash
bash scripts/run-pleno-checkin-nf.sh
```

Ou, se `npm` estiver disponivel:

```bash
npm run pleno-checkin-nf
```

## Evidencias

O robo grava:

```text
outputs/pleno-checkin-nf/relatorio-checkin-*.csv
outputs/pleno-checkin-nf/chaves-erro-checkin-*.csv
outputs/pleno-checkin-nf/chaves-erro-checkin.txt
outputs/pleno-checkin-nf/final.png
```

O arquivo `chaves-erro-checkin.txt` fica pronto para reprocessar somente as chaves que deram erro ou ficaram sem confirmacao. Em caso de erro na automacao, tambem grava screenshots `erro-*.png`.

Mensagens como `NF-e inexistente no INBOUND.` e `ID 144 Portaria 4Tax: Erro desconhecido` entram como erro, sao gravadas nos arquivos de erro e o robo segue para a proxima chave. Mensagens como `NF ja fechada.` entram como OK.

O relatorio CSV e atualizado a cada chave processada. Depois de clicar em `Check in`, o robo monitora somente os filhos diretos de `#mensagem-retorno` como `#mensagem-retorno > .alert` a cada `PLENO_CHECKIN_RESULT_POLL_MS`. Assim que o retorno aparece, grava a linha no CSV e segue para a proxima chave. `PLENO_CHECKIN_RESULT_TIMEOUT_MS` fica apenas como limite maximo de seguranca.

Por padrao, apos cada retorno o robo recarrega a tela de check-in antes da proxima chave. Isso evita que um alerta antigo fique preso na pagina. Se quiser desativar, use `PLENO_CHECKIN_RELOAD_BETWEEN_KEYS=false`.

Para rodar em paralelo, configure `PLENO_CHECKIN_WORKERS` entre `1` e `25`. O robo usa uma fila unica no processo: cada chave e entregue para apenas um worker, evitando duplicidade entre instancias.
