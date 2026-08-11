# Book-it Babi

Aplicação de descoberta e recomendação de livros com backend em FastAPI, interface em Streamlit e integração com Google Books e Open Library.

Versão da API nesta rodada: `0.3.0`.

## O que mudou nesta revisão

- busca por **Livro** e **Autor** são fluxos distintos
- autor é resolvido como entidade da Open Library antes de carregar sua bibliografia
- recomendações exigem uma obra-base concreta; apenas um nome de autor não escolhe mais o primeiro livro retornado
- paginação foi adicionada às buscas de livros e autores
- o modelo diferencia provider, Work, Edition e ISBNs
- deduplicação prioriza ISBN, Work/Edition ID e só depois título + autores normalizados
- taxonomia canônica PT/EN diferencia gênero, subgênero, público, formato e tema, incluindo categorias frequentes dos providers
- busca de livros combina Google Books e Open Library, ranqueia o conjunto e mescla metadados duplicados
- a preferência de idioma só é enviada aos providers quando o usuário a escolhe explicitamente
- normalização trata acentos, pontuação, iniciais e aliases comuns de categoria
- títulos como `Catch-22` e `Spider-Man: Blue` não são mais truncados
- matching temático usa palavras/frases, evitando falsos positivos por substring
- filtros de páginas e ano excluem metadados desconhecidos por padrão
- afinidade é calibrada em `0.0` a `1.0` conforme a evidência disponível, sem punir metadados ausentes como incompatibilidade
- cada recomendação expõe componentes do score e cobertura de metadados para inspeção
- a interface removeu cards introdutórios e textos explicativos redundantes
- clientes HTTP são reaproveitados em vez de recriados a cada chamada
- dependências foram fixadas e uma suíte de regressão foi adicionada

## Requisitos

- Python 3.10+

## Instalação

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Para desenvolvimento e testes:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Variáveis de ambiente

Configure `GOOGLE_BOOKS_API_KEY` em produção para identificar as requisições públicas ao Google Books. Sem a chave, o aplicativo ainda tenta o provider e mantém fallback para Open Library, mas fica mais sujeito a limites e indisponibilidade.

Outras opções:

| Variável | Padrão | Uso |
|---|---:|---|
| `BOOKIT_BASE_URL` | `http://localhost:8000` | Backend usado pelo Streamlit |
| `BOOKIT_REQUEST_TIMEOUT_SECONDS` | `30` | Timeout do frontend |
| `BOOKIT_CACHE_TTL_SECONDS` | `21600` | TTL do cache em memória |
| `BOOKIT_CACHE_MAX_ITEMS` | `512` | Limite de itens em cache |
| `BOOKIT_GOOGLE_COOLDOWN_SECONDS` | `900` | Cooldown após quota/indisponibilidade |
| `BOOKIT_MIN_RECOMMENDATION_SCORE` | `0.34` | Afinidade mínima aceita |
| `BOOKIT_MAX_SEARCH_TERMS` | `6` | Termos temáticos por recomendação |
| `BOOKIT_HTTP_SSL_VERIFY` | `true` | Verificação TLS do backend |

## Execução

Backend:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend, em outro terminal:

```bash
streamlit run cli.py
```

Também é possível usar `./start.sh` em ambientes que fornecem a variável `PORT`.

## Fluxos da interface

### Livro

1. informe o título
2. use o autor apenas como desambiguação opcional
3. confirme visualmente a obra-base
4. configure filtros
5. gere as recomendações

### Autor

1. pesquise o nome da pessoa
2. selecione a entidade correta
3. carregue a bibliografia
4. escolha uma obra concreta
5. gere recomendações a partir dela

## Endpoints

### `GET /search`

Busca obras-base.

- `q`: título, termo ou ISBN obrigatório
- `author`: desambiguação opcional
- `max_results`: `1` a `40`
- `offset`: paginação

### `GET /authors/search`

Busca entidades de autor.

- `q`: nome obrigatório
- `limit`: `1` a `50`
- `offset`: paginação

### `GET /authors/{author_id}/works`

Carrega obras de um autor da Open Library.

- `author_name`: nome exibido, obrigatório
- `limit`: `1` a `100`
- `offset`: paginação

### `GET /recommend`

Recomenda livros a partir de uma obra-base.

Parâmetros principais:

- `reference_id`: ID da obra selecionada
- `q`: título usado quando não há `reference_id` ou como fallback
- `author`: apenas para desambiguar o título
- `category`, `language`
- `min_pages`, `max_pages`
- `min_year`, `max_year`
- `exclude_same_author`
- `include_unknown_metadata`: mantém livros sem páginas/ano apesar de filtros numéricos
- `limit`: `1` a `20`

Uma requisição apenas com `author` retorna `422`; use os endpoints de autor e selecione uma obra.

### `GET /health`

Retorna status, versão da API e presença da chave do Google Books.

## Modelo de livro

Além dos metadados de exibição, cada livro agora expõe:

- `provider`: `google_books`, `open_library` ou `unknown`
- `work_id`
- `edition_id`
- `isbn_10[]`
- `isbn_13[]`

Esses campos evitam tratar Work, Edition e Volume como se fossem o mesmo identificador. Quando o mesmo livro aparece nos dois providers, categorias, descrição, capa, ISBNs e demais campos complementares são mesclados.

As recomendações também incluem:

- `score`: afinidade calibrada entre `0.0` e `1.0`; não representa probabilidade
- `score_components`: similaridade observada em taxonomia, temas, estilo, texto, autor, período, páginas, título e idioma
- `score_coverage`: fração dos sinais para os quais havia metadado comparável

Faixas usadas na interface e na calibração:

- `0.70–1.00`: afinidade forte
- `0.50–0.69`: afinidade relevante
- `0.34–0.49`: resultado exploratório
- abaixo de `0.34`: descartado por padrão

Categorias amplas como `Fiction`, `Nonfiction`, `General` e `Literature` são evidência fraca. Elas não bastam, sozinhas, para sustentar uma recomendação.

## Testes

A suíte cobre regressões de:

- acentos, pontuação e nomes com iniciais
- preservação de títulos legítimos
- aliases de categoria PT/EN e relações entre gênero/subgênero
- geração de termos canônicos para os providers
- categorias comuns dos providers, como `Literary Criticism`, `Health & Fitness`, `Family & Relationships` e `Body, Mind & Spirit`
- falsos temas causados por substrings
- filtros com metadados desconhecidos
- calibração de afinidade para livros fortes, fracos e com metadados esparsos
- componentes e cobertura do score
- parsing de Work/Edition/ISBN
- busca combinada e mesclagem de metadados entre providers
- busca por ISBN nos dois providers
- rejeição de recomendação somente por autor
- paginação do Google Books por `startIndex`
