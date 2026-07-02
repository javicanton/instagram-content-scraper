# instagram-content-scraper

Herramienta open source en Python para **investigación por hashtags en Instagram**: scrape de publicaciones y comentarios, filtro de idioma, análisis de sentimiento, clustering de narrativas, clasificación de discurso y grafos de red.

Basada en [instatouch](https://github.com/drawrowfly/instagram-scraper). **CLI + CSV**, sin APIs de pago.

**Grafos interactivos (ejemplo):** [https://javicanton.github.io/instagram-content-scraper/](https://javicanton.github.io/instagram-content-scraper/)

**Guía completa:** [INSTRUCCIONES.md](INSTRUCCIONES.md)

---

## Empezar en 3 pasos

```bash
git clone https://github.com/<tu-usuario>/instagram-content-scraper.git
cd instagram-content-scraper
chmod +x setup.sh && ./setup.sh
cp .env.example .env
cp instagram_cookie.txt.example instagram_cookie.txt
# Pega tu sessionid de Instagram en instagram_cookie.txt
```

### 1. Define tus hashtags

```bash
cp hashtags.example.csv hashtags.csv
# Edita hashtags.csv: un hashtag por línea, sin #
```

Para **varios corpus** (comparar temas):

```bash
cp corpora.example.yaml corpora.yaml
# Edita corpora.yaml: id + ruta a cada CSV de hashtags
```

### 2. Scrapear

```bash
source .venv/bin/activate

# Un corpus
python orchestrator.py --mode hashtags \
  --hashtag-file hashtags.csv \
  --output-dir data/output/mi_corpus \
  --corpus-id mi_corpus \
  --with-comments --resume

# Varios corpus (lee corpora.yaml)
python orchestrator.py --mode multi \
  --output-dir data/output \
  --with-comments --resume
```

### 3. Analizar

```bash
python analyze.py --step all \
  --input-dir data/output/mi_corpus \
  --output-dir data/analysis/mi_corpus \
  --n-clusters 10 \
  --export-metrics
```

Salidas con sufijo: `clusters_summary_mi_corpus.csv`, `graph_mi_corpus.graphml`, etc.

---

## Caso de estudio incluido

El repositorio incluye un **ejemplo académico** (discursos en Instagram) en `examples/`:

| Archivo | Descripción |
| ------- | ----------- |
| `examples/hashtags_manosfera.csv` | Hashtags de contexto ideológico |
| `examples/hashtags_violencia.csv` | Hashtags de violencia sexual digital |
| `examples/analysis/` | Resúmenes, métricas y grafos GraphML de ejemplo |

Los datos brutos scrapeados (`data/raw/`, `data/output/`) **no** se versionan. Los CSV con texto literal de comentarios tampoco (datos personales).

---

## Grafos interactivos en GitHub Pages

```bash
# Regenera JSON desde examples/analysis/ → docs/graphs/
python publish_graphs.py

git add docs/ && git commit -m "Update interactive graphs"
git push
```

En GitHub: **Settings → Pages → Build and deployment → GitHub Actions**.

El workflow `.github/workflows/pages.yml` publica `docs/` automáticamente al hacer push.

También puedes exportar un grafo concreto:

```bash
python export_graph_web.py \
  --input data/analysis/mi_corpus/graph_hashtags_mi_corpus.graphml \
  --corpus-id mi_corpus \
  --graph-type hashtags \
  --max-nodes 200
```

---

## Modos de scrape

| Modo | Uso |
| ---- | --- |
| `hashtag` | Un hashtag (`--query masculinidad`) |
| `hashtags` | CSV propio (`--hashtag-file hashtags.csv`) |
| `multi` / `dual` | Varios corpus desde `corpora.yaml` |

Flags útiles: `--resume`, `--repair-posts`, `--force-comments`, `--import-raw`.

---

## Pipeline de análisis

| Paso | Qué hace |
| ---- | -------- |
| `lang` | Filtro de idioma (default: solo español) + sentimiento |
| `prep` | Limpieza de texto, metadatos |
| `cluster` | Clustering TF-IDF + K-means |
| `graph` | Grafos hashtags / usuarios / red completa |
| `discourse-init` | Plantillas para tu taxonomía manual |
| `discourse-apply` | Aplica categorías y reconstruye grafos |

Por defecto `--languages es`. Polarización en `sentiment_summary_<corpus>.csv`. Ver [INSTRUCCIONES.md](INSTRUCCIONES.md).

---

## Estructura del proyecto

```
instagram-content-scraper/
├── orchestrator.py          # Fase 1: scraping
├── analyze.py               # Fase 2: análisis
├── export_graph_web.py      # GraphML → JSON web
├── publish_graphs.py        # Regenera docs/graphs/
├── hashtags.example.csv     # Plantilla de hashtags
├── corpora.example.yaml     # Plantilla multi-corpus
├── examples/                # Caso de estudio + salidas de ejemplo
├── docs/                    # GitHub Pages (visor interactivo)
├── data/
│   ├── output/              # Tu scrape (gitignored)
│   ├── raw/                 # Crudo instatouch (gitignored)
│   └── analysis/            # Tu análisis (gitignored)
└── INSTRUCCIONES.md
```

---

## Consideraciones legales y éticas

- El scraping puede violar los ToS de Instagram/Meta.
- Comentarios y perfiles son **datos personales**: no publiques CSV con texto crudo sin anonimizar.
- Usa la herramienta con finalidad investigadora legítima y documenta el tratamiento de datos (RGPD/LOPD).

## Licencia

MIT — ver [LICENSE](LICENSE). `instatouch` tiene licencia MIT propia.
