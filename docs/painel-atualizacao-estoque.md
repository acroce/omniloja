# Painel de Atualizacao de Estoque

No diretorio do projeto, inicie o painel com:

```bash
npm run atualizar-estoque
```

Abra `http://127.0.0.1:8110` no navegador. Escolha as datas, execute a rotina e, ao terminar, use **Baixar arquivo final** ou **Abrir pasta do resultado**.

O painel usa o estoque atual do MySQL do Pleno, inclui somente notas do CD 704 sem check-in e preserva o layout do CSV. Produtos presentes apenas nas notas continuam fora do arquivo final.
