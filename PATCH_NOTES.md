# Notas de aplicação do patch

## Mudança incompatível intencional

`GET /recommend?author=...` não escolhe mais uma obra arbitrária. O fluxo correto é:

1. `GET /authors/search?q=...`
2. `GET /authors/{author_id}/works?author_name=...`
3. selecionar uma obra
4. chamar `GET /recommend?reference_id=...`

## Compatibilidade de resposta

`BookResponse` ganhou os campos `provider`, `work_id`, `edition_id`, `isbn_10` e `isbn_13`. Os campos anteriores foram preservados.

## Política de filtros

Quando `min_pages`, `max_pages`, `min_year` ou `max_year` estão ativos, resultados sem esse metadado são excluídos. Para manter o comportamento permissivo anterior, envie `include_unknown_metadata=true`.

## Validação recomendada após aplicar

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q .
```


## Rodada de taxonomia, busca e afinidade

Esta rodada é incremental sobre o primeiro patch e altera principalmente:

- `taxonomy.py`: taxonomia canônica PT/EN, relações entre categorias e termos de busca
- `book_profile.py`: sinais temáticos e estilísticos alimentados pela taxonomia
- `filters.py`: score normalizado pela evidência disponível, com componentes e cobertura
- `main.py`: busca simultânea nos dois providers, ranking unificado e mesclagem de duplicados
- `cli.py`: remoção do bloco introdutório, textos redundantes e exibição da afinidade em percentual

O valor de `score` deve ser lido como afinidade relativa com a obra-base, não como probabilidade. O padrão de `BOOKIT_MIN_RECOMMENDATION_SCORE` passa de `0.18` para `0.34` porque a escala foi recalibrada.

A calibração evita dois erros opostos:

- metadados ausentes não são tratados automaticamente como incompatibilidade
- coincidências editoriais fracas, como idioma, ano, páginas ou apenas `Fiction`/`Nonfiction`, não sustentam uma nota alta

As categorias canônicas agora cobrem gêneros, subgêneros, público, formato e temas frequentes do Google Books/Open Library. Relações de pai/subgênero e famílias específicas são usadas no score e na geração dos termos de busca; rótulos genéricos têm peso reduzido.

`GET /search` aceita ISBN e consulta esse campo diretamente tanto no Google Books quanto na Open Library.

A busca temática não herda mais automaticamente o idioma da obra-base. A preferência só é enviada aos providers quando o filtro correspondente é escolhido pelo usuário; o filtro final continua estrito na aplicação.
