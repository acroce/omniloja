# Robo de login no Pleno

Este robo abre o Chrome, acessa `https://172.22.20.101/Index` e preenche o login do Pleno usando Playwright.

## Configuracao

Copie o exemplo para o `.env` do projeto e preencha suas credenciais:

```bash
cp .env.pleno.example .env
```

Edite:

```dotenv
PLENO_USER=seu_usuario
PLENO_PASSWORD=sua_senha
```

## Execucao

```bash
npm run pleno-login
```

Se `npm` ou `node` nao estiverem no PATH da maquina, rode pelo atalho:

```bash
bash scripts/run-pleno-login.sh
```

O Chrome fica aberto apos o login. Para encerrar, pressione `Ctrl+C` no terminal.

## Ajuste de seletores

Se o site mudar ou o robo nao encontrar algum campo, informe os seletores no `.env`:

```dotenv
PLENO_USER_SELECTOR=#usuario
PLENO_PASSWORD_SELECTOR=#senha
PLENO_SUBMIT_SELECTOR=#btnEntrar
```

O script salva evidencias em `outputs/pleno-login/apos-login.png` ou `outputs/pleno-login/erro-login.png`.
