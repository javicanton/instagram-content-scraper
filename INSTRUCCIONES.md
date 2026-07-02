# Instrucciones de uso — instagram-content-scraper

Herramienta open source para investigación por **hashtags en Instagram**: recolección, detección de idioma, polarización del lenguaje, clustering, discurso y grafos.

**Configura tus propias listas de hashtags** (`hashtags.csv` o `corpora.yaml`). El repositorio incluye un **caso de estudio de ejemplo** en `examples/` (investigación académica sobre discursos en Instagram).

**Grafos interactivos:** [https://javicanton.github.io/instagram-content-scraper/](https://javicanton.github.io/instagram-content-scraper/) — publicables con `python publish_graphs.py`.

---

## Configurar tus hashtags

### Un solo corpus

```bash
cp hashtags.example.csv hashtags.csv
```

Edita `hashtags.csv`: **un hashtag por línea, sin `#`**. También admite CSV con cabecera `hashtag`.

### Varios corpus (comparar temas)

```bash
cp corpora.example.yaml corpora.yaml
```

Ejemplo en `corpora.example.yaml`:

```yaml
corpora:
  - id: tema_a
    hashtags_file: hashtags_tema_a.csv
  - id: tema_b
    hashtags_file: hashtags_tema_b.csv
```

Cada corpus se guarda en `data/output/<id>/` y se analiza en `data/analysis/<id>/`.

### Caso de estudio incluido (ejemplos)

| Archivo | Rol |
| ------- | --- |
| `examples/hashtags_manosfera.csv` | Hashtags de contexto ideológico (ejemplo) |
| `examples/hashtags_violencia.csv` | Hashtags de violencia sexual digital (ejemplo) |
| `examples/analysis/` | Salidas del pipeline (resúmenes, grafos) |

> Los datos brutos de Instagram (`data/raw/`, `data/output/`) y los CSV con comentarios literales **no** se suben al repositorio público.

---



## Resumen del flujo

```
1. Instalar y configurar sesión (instagram_cookie.txt)
2. Scrapear por hashtags (modo dual o corpus individual)
3. Filtro de idioma español (default `--languages es`; solo ES entra a prep/cluster)
4. Análisis: prep → clustering → grafos (incluye polarización del lenguaje)
5. Revisar sentimiento por corpus, idioma y cluster
6. Clustering ciego → taxonomía de discurso → `--step discourse-apply`
7. Iterar (hashtags, léxico de sentimiento, categorías)
```

---



## 1. Instalación (solo la primera vez)

```bash
cd instagram-content-scraper

# Dependencias Node (motor instatouch)
npm install

# Entorno Python (script automático — evita conflictos conda/arquitectura)
chmod +x setup.sh
./setup.sh

# Configuración
cp .env.example .env
```

> En cada sesión nueva de Terminal: `cd instagram-content-scraper && source .venv/bin/activate`



### Si falla `python3 -m venv` (conda + arquitectura)

En Mac Apple Silicon con conda `(base)` activo, el `python3` por defecto puede ser **x86_64** mientras conda es **arm64** → el venv queda roto.

```bash
cd instagram-content-scraper
conda deactivate          # repetir hasta que desaparezca (base)
rm -rf .venv
/opt/miniconda3/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

O simplemente: `./setup.sh`

Comprueba que el entorno es arm64:

```bash
python -c "import platform; print(platform.machine())"
# Debe imprimir: arm64
```

---



## 2. Configurar la sesión de Instagram

Instagram exige cookies de sesión activas.

### Opción A — Recomendada: `instagram_cookie.txt`

1. Abre [instagram.com](https://www.instagram.com) en **Chrome** (logueado).
2. **DevTools** (F12) → **Network** → recarga la página.
3. Clic en una petición a `instagram.com` → **Request Headers** → `cookie:`.
4. Copia **todo** el valor (desde `datr=` hasta el final).
5. Pégalo en un archivo nuevo:

```bash
cp instagram_cookie.txt.example instagram_cookie.txt
# Edita instagram_cookie.txt: UNA sola línea, sin comillas envolventes
```

> **No pegues la cookie en** `.env` si incluye `rur="..."` — las comillas internas rompen el parser.



### Opción B — Solo sessionid en `.env`

```env
INSTAGRAM_SESSION_ID=valor_de_sessionid_sin_prefijo
INSTAGRAM_CSRF_TOKEN=valor_de_csrftoken
```



### Comprobar que funciona

```bash
source .venv/bin/activate
python verify_instatouch.py
```

Debes ver: `OK: 3 posts de @natgeo` y `listo para orchestrator.py`

---



## 3. Scrapear por hashtags



### Un hashtag

```bash
source .venv/bin/activate

python orchestrator.py --mode hashtag \
  --query masculinidad \
  --max-posts 80 \
  --max-comments-per-post 150 \
  --with-comments
```

(Sin `#` en `--query`.)

### Varios hashtags desde CSV

Por defecto se usa `hashtags.csv` (copia desde `hashtags.example.csv`). Un hashtag por línea, sin `#`.

```bash
cp hashtags.example.csv hashtags.csv
# edita hashtags.csv

python orchestrator.py --mode hashtags \
  --hashtag-file hashtags.csv \
  --output-dir data/output/mi_corpus \
  --corpus-id mi_corpus \
  --max-posts-per-hashtag 60 \
  --with-comments \
  --max-comments-per-post 100
```

Elegir otro archivo con `--hashtag-file` (ejemplo del caso de estudio):

```bash
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_violencia.csv \
  --output-dir data/output/violencia \
  --corpus-id violencia \
  --max-posts-per-hashtag 30 \
  --with-comments \
  --max-comments-per-post 50
```



### Modo multi: varios corpus (`corpora.yaml`)

Copia `corpora.example.yaml` → `corpora.yaml` y define tus listas. Ejecuta todos en secuencia:

```bash
cp corpora.example.yaml corpora.yaml

python orchestrator.py --mode multi \
  --output-dir data/output \
  --max-posts-per-hashtag 30 \
  --with-comments \
  --max-comments-per-post 50
```

Salidas (ejemplo del caso de estudio con `corpora.example.yaml`):


| Carpeta                  | Corpus (ejemplo)         | Archivos                    |
| ------------------------ | ------------------------ | --------------------------- |
| `data/output/manosfera/` | Contexto ideológico      | `posts.csv`, `comments.csv` |
| `data/output/violencia/` | Violencia sexual digital | `posts.csv`, `comments.csv` |

`--mode dual` es alias de `--mode multi`. Solo un corpus: `--only-corpus violencia`.


Cada fila lleva `**corpus_id**` (`manosfera` o `violencia`). El autor del post va en `profile_username`. La columna `**source_hashtag**` indica desde qué búsqueda se obtuvo cada post.

### Explore sin personalizar

Por defecto se usa la variante **nonpersonalized** de Explore. Configurable en `.env`:

```env
INSTAGRAM_EXPLORE_VARIANT=nonpersonalized
```

Vacío desactiva el parámetro y usa el feed estándar.

### Reanudar, reparar y forzar comentarios


| Flag               | Efecto                                                                 |
| ------------------ | ---------------------------------------------------------------------- |
| `--resume`         | Omite hashtags ya completos; reanuda comentarios a medias              |
| `--repair-posts`   | Corrige `post_url` rotas (CDN → instagram.com/p/…) usando `data/raw/`  |
| `--force-comments` | Re-scrapea comentarios aunque el post ya esté en `comments.csv`        |
| `--import-raw`     | Importa posts desde `data/raw/` para hashtags sin filas en `posts.csv` |


**Recolección principal con reanudación** (recomendado tras interrupciones):

```bash
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_violencia.csv \
  --output-dir data/output/violencia \
  --corpus-id violencia \
  --repair-posts \
  --resume \
  --with-comments \
  --max-posts-per-hashtag 30 \
  --max-comments-per-post 50
```

**Solo reparar URLs y completar comentarios faltantes:**

```bash
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_manosfera.csv \
  --output-dir data/output/manosfera \
  --corpus-id manosfera \
  --repair-posts \
  --resume \
  --with-comments
```

**Re-scrapear comentarios vacíos** (p. ej. tras bug de instatouch):

```bash
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_manosfera.csv \
  --output-dir data/output/manosfera \
  --corpus-id manosfera \
  --force-comments \
  --with-comments \
  --max-comments-per-post 50
```

**Solo un corpus del modo dual:**

```bash
python orchestrator.py --mode dual \
  --only-corpus violencia \
  --resume \
  --with-comments
```



### Filtros opcionales de engagement (por hashtag)

```bash
# Posts con al menos 500 likes
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_violencia.csv \
  --min-likes 500 \
  --with-comments

# Top 20 por likes tras filtrar
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_violencia.csv \
  --top-by likes \
  --keep-top 20 \
  --with-comments
```

---



## 4. Detección y filtro de idioma

**Por defecto `--languages es`:** solo comentarios detectados en **español** entran a `prep`, **clustering** y grafos. PT, EN, `unknown` y `emoji` quedan en `language_excluded_<corpus>.csv`.

Para clusterizar mezclando idiomas (no recomendado), usa explícitamente `--languages all`.

Umbrales por defecto: confianza `0.72`, margen `0.12`. Sube a `0.80`–`0.85` si queda ruido PT/EN.

### Cómo funciona

- Combina **langdetect** + **heurística léxica** (ES/PT/EN).
- Textos **solo emojis** → idioma `emoji` (confianza 1.0), no `unknown`.
- Penaliza mezclas emoji+texto corto antes de clasificar ES/PT/EN.
- Rechaza casos ambiguos (poco margen entre 1.º y 2.º idioma).
- Penaliza PT cuando se pide español.



### Corpus español (default — prep y clustering)

```bash
python analyze.py --step lang \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia

python analyze.py --step lang \
  --input-dir data/output/manosfera \
  --output-dir data/analysis/manosfera
```

Equivalente explícito: `--languages es` (ya es el default). Solo comentarios en español pasan a `comments_for_analysis_violencia.csv`. El resto → `language_excluded_violencia.csv`.

Tras este paso revisa `language_summary_violencia.csv` (debe mostrar sobre todo `es`) y `sentiment_summary_violencia.csv`.

### Detección sin filtrar (todos los idiomas)

Solo si quieres **etiquetar** idioma/sentimiento sin excluir nada (no usar para clustering de la tesis):

```bash
python analyze.py --step lang \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --languages all
```

### Afinar filtro español (más estricto)

```bash
python analyze.py --step lang \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --min-language-confidence 0.80 \
  --min-language-margin 0.15
```

Para incluir comentarios solo emoji además del español: `--languages es,emoji`.

### Salidas


| Archivo                     | Contenido                                     |
| --------------------------- | --------------------------------------------- |
| `comments_for_analysis.csv` | Comentarios que pasan el filtro + sentimiento |
| `language_excluded.csv`     | Excluidos con `exclusion_reason` y scores     |
| `language_summary.csv`      | Recuento por idioma conservado                |
| `sentiment_summary.csv`     | Polarización global del corpus                |
| `sentiment_by_language.csv` | Polarización por idioma (es, pt, en, emoji…)  |




### Motivos de exclusión (`exclusion_reason`)


| Motivo               | Significado                                                        |
| -------------------- | ------------------------------------------------------------------ |
| `emoji_only`         | Solo emojis (`language=emoji`; incluir con `--languages es,emoji`) |
| `unknown_language`   | Muy poco texto o símbolos sin clasificar                           |
| `not_es`             | Detectado PT/EN u otro idioma                                      |
| `low_confidence`     | Confianza por debajo del umbral                                    |
| `ambiguous_language` | ES y PT/EN muy parecidos en score                                  |




### Ajustar umbrales


| Parámetro                   | Default | Cuándo cambiar                                                               |
| --------------------------- | ------- | ---------------------------------------------------------------------------- |
| `--languages`               | `es`    | `all` = sin filtrar; `es,emoji` = español + solo emoji                       |
| `--min-language-confidence` | `0.72`  | Sube a `0.80`–`0.85` si queda ruido PT/EN en el corpus ES                   |
| `--min-language-margin`     | `0.12`  | Sube a `0.15`–`0.18` si hay mezcla ambigua ES/PT                             |
| `--keep-unknown-language`   | off     | Con `--languages es`: incluir comentarios `unknown`                          |


**Filtro estricto** (menos comentarios, más limpio):

```bash
python analyze.py --step lang \
  --input-dir data/output/manosfera \
  --output-dir data/analysis/manosfera \
  --languages es \
  --min-language-confidence 0.80 \
  --min-language-margin 0.15
```

**Revisar manualmente los excluidos:**

```bash
# Abre language_excluded.csv y filtra exclusion_reason = not_es o low_confidence
# Ajusta umbrales y relanza --step lang
```



### Resultados de referencia con `--languages es` (umbrales 0.72 / 0.12)


| Corpus    | Comentarios con texto | Conservados (ES) | Excluidos |
| --------- | --------------------- | ---------------- | --------- |
| violencia | ~1.714                | ~466             | ~1.248    |
| manosfera | ~6.324                | ~1.245           | ~5.079    |


La mayoría de excluidos son `unknown`, PT/EN explícitos o `emoji`. Con el default `es`, **solo entra al clustering el subconjunto en español**.

---



## 5. Análisis completo (clustering + grafos)

### Convención de nombres de salida

Todos los CSV y grafos del análisis llevan **sufijo del corpus** para poder repetir el pipeline sin sobrescribir resultados:

- Patrón: `{archivo}_{corpus}.{ext}` (p. ej. `clusters_summary_violencia.csv`, `graph_manosfera.graphml`)
- El sufijo se toma del nombre de `--output-dir` (`data/analysis/violencia` → `violencia`) o de `--corpus-id` si lo indicas
- Puedes analizar violencia y manosfera en paralelo en carpetas distintas sin mezclar archivos

```bash
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --n-clusters 10 \
  --min-comment-length 15 \
  --export-metrics
```

Repite con `--input-dir data/output/manosfera` para el corpus de contexto.

> **`--step all` usa `--languages es` por defecto.** El clustering solo incluye comentarios en español. Sube `--min-language-confidence` si ves ruido PT/EN en `comments_enriched_violencia.csv` (o el sufijo de tu corpus).

### Pasos del pipeline


| Paso  | Flag              | Qué hace                                                                             |
| ----- | ----------------- | ------------------------------------------------------------------------------------ |
| 0     | `lang`            | Filtra a **español** (default) + sentimiento → `comments_for_analysis_<corpus>.csv` |
| 1     | `prep`            | Limpieza, stopwords, spam, sentimiento, discurso = `pending`                         |
| 2     | `cluster`         | K-means + TF-IDF + `sentiment_by_cluster_<corpus>.csv`                               |
| 3     | `graph`           | Grafos hashtags, usuarios, red completa                                              |
| 4     | `discourse-init`  | Genera `cluster_labels_<corpus>.csv` + `discourse_taxonomy_<corpus>.json`            |
| 5     | `discourse-apply` | Aplica taxonomía, retroalimenta léxico, re-etiqueta comentarios y posts              |
| `all` | —                 | Ejecuta lang → prep → cluster → graph (sin discurso; hazlo después con tu taxonomía) |




### Filtro temporal (`--date-from` / `--date-to`)

Opcionales. Formato `YYYY-MM-DD`. Filtran **posts** por `published_at`; los comentarios de posts descartados también se excluyen.

```bash
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --date-from 2024-01-01 \
  --date-to 2024-12-31 \
  --export-metrics
```

> El scraper no pide rango de fechas a Instagram: solo filtra lo ya descargado.



### Clasificación de discurso (flujo en dos fases)

**Fase 1 — automática (clustering ciego):** `prep` y `cluster` no asignan categorías teóricas. Los comentarios quedan con `discourse_source=pending`. Revisa `clusters_summary_violencia.csv` (`top_terms`, `representative_comments`).

**Fase 2 — manual + retroalimentación:** Tras tu lectura, defines categorías y mapeas clusters:

```bash
# Tras --step all o --step cluster
python analyze.py --step discourse-init \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia
```

Genera en `data/analysis/violencia/` (sufijo `_violencia` en cada archivo):


| Archivo                              | Qué editas                                                      |
| ------------------------------------ | --------------------------------------------------------------- |
| `discourse_taxonomy_violencia.json`  | Categorías del estudio (`id`, `label`, `description`, `terms`)  |
| `cluster_labels_violencia.csv`       | Por cada `cluster_id`: `discourse_category_id` + `reviewed=yes` |


Plantilla de categorías: `discourse_taxonomy.example.json` en la raíz del proyecto.

**Cuando tengas la taxonomía lista** (o me la pases para cargarla):

```bash
python analyze.py --step discourse-apply \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --export-metrics
```

Qué hace `discourse-apply`:

1. Etiqueta comentarios según el mapeo cluster → categoría (`discourse_source=cluster`).
2. Construye `discourse_lexicon_violencia.json` del corpus: términos de la taxonomía + `top_terms` de clusters revisados.
3. Re-etiqueta comentarios no mapeados con el léxico (`discourse_source=lexical`).
4. Genera `posts_discourse_violencia.csv` (discurso dominante por post + caption).
5. Actualiza `clusters_summary_violencia.csv` y reconstruye grafos con nombres de categoría.

Columnas clave en `comments_clustered_violencia.csv`:


| Columna                    | Significado                                            |
| -------------------------- | ------------------------------------------------------ |
| `discourse_category_id`    | ID de categoría (p. ej. `legitimacion_trivializacion`) |
| `discourse_category_label` | Etiqueta legible                                       |
| `discourse_source`         | `cluster`, `lexical`, `pending` o `unlabeled`          |
| `discourse_signals`        | Términos léxicos que dispararon la etiqueta            |


> El léxico global `discourse_lexicon.json` en la raíz queda como referencia legacy; cada corpus usa el suyo en `data/analysis/<corpus>/discourse_lexicon_<corpus>.json`.

---



## 6. Polarización del lenguaje (cómo aplicarlo)

No hay un `--step` aparte: el **sentimiento se calcula automáticamente** en `lang`, `prep`, `cluster` y `all`. Clasifica cada comentario como **positive**, **negative** o **neutral** y calcula un score de polaridad.

### Aplicar en un corpus (recomendado: análisis completo)

```bash
source .venv/bin/activate

# Violencia — solo español (default) + sentimiento + clusters + grafos
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --n-clusters 20 \
  --min-comment-length 15 \
  --export-metrics

# Manosfera — repetir con su carpeta
python analyze.py --step all \
  --input-dir data/output/manosfera \
  --output-dir data/analysis/manosfera \
  --n-clusters 20 \
  --min-comment-length 15 \
  --export-metrics
```

En consola verás líneas como `Sentimiento: {'neutral': 415, 'negative': 34, ...}` y `Polarización (corpus): {'all': 0.42}`.

### Solo sentimiento (sin re-clusterizar)

Útil tras editar `sentiment_lexicon.json` o para una vista rápida de todo el corpus scrapeado:

```bash
# Todos los comentarios con texto (incluye los que prep descartará después)
python analyze.py --step lang \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia

# Sentimiento solo sobre comentarios que entran al NLP (prep)
python analyze.py --step prep \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia

# Añadir polarización por cluster (requiere comments_enriched_violencia.csv previo)
python analyze.py --step cluster \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --n-clusters 10
```



### Qué archivos revisar (orden sugerido)

1. `sentiment_summary_<corpus>.csv` — visión global del corpus (`positive_pct`, `negative_pct`, `neutral_pct`, `polarization_index`).
2. `sentiment_by_language_<corpus>.csv` — compara ES vs PT vs EN vs `emoji`.
3. `sentiment_by_cluster_<corpus>.csv` — qué narrativas (clusters) son más polarizadas.
4. `clusters_summary_<corpus>.csv` — columnas `mean_polarity` y `polarization_index` junto a `top_terms`.
5. `comments_enriched_<corpus>.csv` o `comments_clustered_<corpus>.csv` — filtra por `sentiment_label` y lee `sentiment_signals`.



### Columnas por comentario


| Columna                    | Significado                                  |
| -------------------------- | -------------------------------------------- |
| `sentiment_label`          | `positive`, `negative` o `neutral`           |
| `sentiment_polarity`       | −1 (muy negativo) … +1 (muy positivo)        |
| `sentiment_positive_score` | Peso de señales positivas detectadas         |
| `sentiment_negative_score` | Peso de señales negativas detectadas         |
| `sentiment_signals`        | Términos/emojis que dispararon la puntuación |




### Cómo se calcula

Motor: `sentiment.py` + `sentiment_lexicon.json` (editable en la raíz del proyecto).

- Léxico positivo/negativo por idioma (`es`, `pt`, `en`), según columna `language`.
- Emojis con carga afectiva (p. ej. ❤️👏 vs 😡💀); comentarios solo emoji usan solo emojis.
- **Negadores** (`no`, `nunca`, `not`…) invierten la polaridad de un término cercano.
- **Intensificadores** (`muy`, `very`, `muito`…) amplían la señal.

**Índice de polarización** (`polarization_index`): `(positivos + negativos) / total`. Valor **alto** = más comentarios emocionalmente cargados (menos neutros). `mean_polarity` indica si el balance global inclina a positivo o negativo.

### Personalizar el léxico

Edita `sentiment_lexicon.json` y relanza `prep` o `all`:

```json
{
  "positive": {
    "es": ["excelente", "apoyo", "..."],
    "pt": ["obrigado", "..."],
    "en": ["thanks", "..."]
  },
  "negative": {
    "es": ["asco", "violencia", "..."],
    "pt": ["nojo", "..."],
    "en": ["hate", "..."]
  },
  "emoji_positive": ["❤", "👏", "..."],
  "emoji_negative": ["😡", "💀", "..."]
}
```

Para términos del dominio (p. ej. «falsa denuncia», «dictadura feminazi»), añádelos en `negative.es` si quieres capturarlos como carga negativa en el análisis de polarización (independiente de la taxonomía de discurso).

### Comparar manosfera vs violencia

```bash
# Tras --step all en ambos corpus, abre en Excel/Numbers:
#   data/analysis/manosfera/sentiment_summary_manosfera.csv
#   data/analysis/violencia/sentiment_summary_violencia.csv
# Compara polarization_index y negative_pct entre corpora.
```

Cruza con clusters: un cluster con alto `polarization_index` y `mean_polarity` negativo puede ser candidato a revisión manual antes de asignar categoría de discurso.

### Afinar filtro español (opcional)

Ya es el default; sube umbrales si queda ruido:

```bash
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --languages es \
  --min-language-confidence 0.72 \
  --min-language-margin 0.12 \
  --n-clusters 10 \
  --export-metrics
```

> Análisis **léxico/heurístico**, no un modelo de deep learning. Valida siempre con lectura manual de muestras (`sentiment_signals` ayuda a auditar).



### Salidas del análisis (resto)


| Archivo                                      | Para qué sirve                                      |
| -------------------------------------------- | --------------------------------------------------- |
| `comments_for_analysis_<corpus>.csv`         | Corpus filtrado por idioma                          |
| `language_excluded_<corpus>.csv`             | Comentarios descartados por idioma                  |
| `language_summary_<corpus>.csv`              | Recuento de idiomas                                 |
| `clusters_summary_<corpus>.csv`              | **Empieza aquí**: términos y ejemplos por narrativa |
| `comments_clustered_<corpus>.csv`            | Cada comentario con su `cluster_id`                 |
| `comments_enriched_<corpus>.csv`             | Texto limpio + sentimiento + discurso + metadatos   |
| `sentiment_summary_<corpus>.csv`             | Polarización global (positivo/negativo/neutral)     |
| `sentiment_by_language_<corpus>.csv`         | Polarización por idioma                             |
| `sentiment_by_cluster_<corpus>.csv`          | Polarización por cluster                            |
| `posts_discourse_<corpus>.csv`               | Discurso por post (caption + comentarios)           |
| `discourse_category_summary_<corpus>.csv`    | Recuento por categoría tras discourse-apply         |
| `discourse_taxonomy_<corpus>.json`           | Taxonomía editable del corpus                       |
| `cluster_labels_<corpus>.csv`                | Mapeo cluster → categoría (tu revisión)             |
| `discourse_lexicon_<corpus>.json`            | Léxico del corpus (generado desde taxonomía)        |
| `network_metrics_<corpus>.csv`               | Degree, betweenness, eigenvector, comunidad         |
| `graph_<corpus>.graphml`                     | Red completa para Gephi                             |
| `graph_hashtags_<corpus>.graphml`            | Co-ocurrencia de hashtags                           |
| `graph_users_<corpus>.graphml`               | Menciones y co-comentario                           |
| `edges_hashtags_<corpus>.csv`                | Aristas de hashtags                                 |
| `edges_users_<corpus>.csv`                   | Red entre comentaristas                             |
| `edges_social_<corpus>.csv`                  | Menciones y co-comentario                           |
| `edges_narrative_<corpus>.csv`               | Quién alimenta qué narrativa                        |




### Variantes de análisis

```bash
# Solo prep (sin re-clusterizar; filtra a español por default)
python analyze.py --step prep \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia

# Solo clustering (si ya tienes comments_enriched_violencia.csv)
python analyze.py --step cluster \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --n-clusters 12

# Solo reconstruir grafos
python analyze.py --step graph \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --export-metrics

# Todos los idiomas en clusters (no recomendado para la tesis)
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --languages all \
  --n-clusters 10 \
  --export-metrics

# Filtro ES más estricto + más clusters
python analyze.py --step all \
  --input-dir data/output/manosfera \
  --output-dir data/analysis/manosfera \
  --min-language-confidence 0.80 \
  --min-language-margin 0.15 \
  --n-clusters 15 \
  --min-comment-length 10 \
  --export-metrics
```

---



## 7. Interpretar clusters y definir categorías (manual)

Los clusters son **candidatos**, no categorías finales:

1. Abre `clusters_summary_violencia.csv` (mira también `polarization_index` y `mean_polarity`).
2. Para cada `narrativa_N`: lee `top_terms` y `representative_comments`.
3. Opcional: filtra comentarios del cluster en `comments_clustered_violencia.csv` por `sentiment_label`.
4. Ejecuta `--step discourse-init` y completa `discourse_taxonomy_violencia.json` con tus categorías teóricas.
5. En `cluster_labels_violencia.csv`, asigna cada `cluster_id` a un `discourse_category_id` y marca `reviewed=yes`.
6. Ejecuta `--step discourse-apply` para propagar etiquetas a comentarios y posts.
7. Opcional: importa en **MAXQDA** o **R**.

---



## 8. Visualizar grafos

### GitHub Pages (interactivo en el navegador)

**Ejemplo publicado:** [https://javicanton.github.io/instagram-content-scraper/](https://javicanton.github.io/instagram-content-scraper/)

Tras el análisis, exporta grafos de hashtags para el visor web en `docs/`:

```bash
# Desde examples/analysis/ (incluido en el repo) o tu data/analysis/<corpus>/
python publish_graphs.py

# Un grafo concreto
python export_graph_web.py \
  --input data/analysis/violencia/graph_hashtags_violencia.graphml \
  --corpus-id violencia \
  --min-degree 30 \
  --output docs/graphs/hashtags_violencia.json
```

Publicación:

1. Haz push de la carpeta `docs/` (incluye `index.html`, `viewer.html`, `graphs/*.json`).
2. En GitHub: **Settings → Pages → Build and deployment → GitHub Actions**.
3. El workflow `.github/workflows/pages.yml` despliega automáticamente.

El visor usa [vis-network](https://visjs.org/). Incluye el grafo completo de hashtags; filtra en el navegador por **grado mínimo** (por defecto: manosfera ≥ 33, violencia ≥ 30) y peso de arista. Los colores representan comunidades detectadas en el GraphML (Louvain).

### Gephi (análisis avanzado)

1. Instala [Gephi](https://gephi.org/).
2. **File → Open** → `graph_violencia.graphml` o `graph_hashtags_violencia.graphml`.
3. **Statistics** → Modularity, Average Degree.
4. Layout: **ForceAtlas 2**.
5. **Appearance → Nodes → Color** → partition por `node_type`:
  - `user` = comentaristas
  - `hashtag` = etiquetas
  - `narrative` = cluster de narrativa
6. **Appearance → Edges → Size** → weight.

---



## 9. Iterar y ampliar la muestra

```bash
# 1. Añade hashtags a tu hashtags.csv o edita corpora.yaml

# 2. Relanza scrape (incremental con --resume)
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_violencia.csv \
  --output-dir data/output/violencia \
  --corpus-id violencia \
  --resume \
  --with-comments \
  --max-posts-per-hashtag 40

# 3. Re-analiza (solo español por defecto; sube umbrales si hace falta)
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --min-language-confidence 0.80 \
  --n-clusters 10 \
  --export-metrics
```

---



## 10. Comandos útiles de referencia

```bash
# Activar entorno (siempre al abrir Terminal)
source .venv/bin/activate

# Dual corpus completo
python orchestrator.py --mode dual \
  --max-posts-per-hashtag 30 \
  --with-comments \
  --max-comments-per-post 50 \
  --resume \
  --repair-posts

# Corpus violencia con reanudación
python orchestrator.py --mode hashtags \
  --hashtag-file examples/hashtags_violencia.csv \
  --output-dir data/output/violencia \
  --corpus-id violencia \
  --resume \
  --repair-posts \
  --with-comments

# Tras revisar clusters: generar plantillas de discurso
python analyze.py --step discourse-init \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia

# Aplicar taxonomía (cuando cluster_labels_violencia.csv esté completo)
python analyze.py --step discourse-apply \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --export-metrics

# Filtro solo español (estricto)
python analyze.py --step lang \
  --input-dir data/output/manosfera \
  --output-dir data/analysis/manosfera \
  --languages es \
  --min-language-confidence 0.80 \
  --min-language-margin 0.15

# Análisis completo violencia (idioma + sentimiento + clusters + grafos)
python analyze.py --step all \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --n-clusters 10 \
  --export-metrics

# Solo polarización rápida (todo el corpus scrapeado)
python analyze.py --step lang \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia

# Tras editar sentiment_lexicon.json
python analyze.py --step prep \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia
python analyze.py --step cluster \
  --input-dir data/output/violencia \
  --output-dir data/analysis/violencia \
  --n-clusters 10

# Verificar sesión
python verify_instatouch.py
```

---



## 11. Problemas frecuentes


| Síntoma                                         | Solución                                                                |
| ----------------------------------------------- | ----------------------------------------------------------------------- |
| `INSTAGRAM_SESSION_ID no está definido`         | Copia `.env.example` → `.env` o usa `instagram_cookie.txt`              |
| Comentarios con likes pero `comment_text` vacío | Relanza con `--force-comments --with-comments`                          |
| `post_url` apunta a CDN                         | `--repair-posts` antes de scrapear comentarios                          |
| ~1.500 comentarios PT/EN en análisis            | Verifica que no uses `--languages all`; sube `--min-language-confidence`  |
| Muchos `unknown_language` excluidos             | Texto muy corto; los solo emoji van como `emoji` (no `unknown`)         |
| `rate limit`                                    | Sube `INSTATOUCH_TIMEOUT_MS=5000` en `.env`; espera 10–15 min           |
| CSV vacío                                       | Sesión expirada → renueva cookie                                        |
| Pocos clusters / grafo vacío                    | Baja `--min-comment-length`, baja umbral de idioma, o scrapea más posts |
| Casi todo `sentiment_label=neutral`             | Amplía términos en `sentiment_lexicon.json` y relanza `--step prep`     |
| Sentimiento no cuadra con lectura manual        | Revisa `sentiment_signals`; ajusta léxico (negación/intensificadores)   |
| `ImportError: incompatible architecture`        | `conda deactivate` → `rm -rf .venv` → `./setup.sh`                      |
| `MaxListenersExceededWarning`                   | Inofensivo; usa `python verify_instatouch.py`                           |


---



## 12. Consideraciones éticas

- El scraping puede violar los Términos de Servicio de Instagram/Meta.
- Los comentarios contienen **datos personales**: minimiza conservación, anonimiza en publicaciones.
- Usa los datos solo para investigación con finalidad legítima.
- Documenta el tratamiento de datos en tu memoria o artículo (RGPD/LOPD).

---



## Estructura de carpetas

```
instagram-content-scraper/
├── instagram_cookie.txt          ← sesión (NO commitear)
├── hashtags.example.csv            ← plantilla: copia → hashtags.csv
├── corpora.example.yaml            ← plantilla multi-corpus
├── examples/
│   ├── hashtags_manosfera.csv    ← caso de estudio (ejemplo)
│   ├── hashtags_violencia.csv
│   └── analysis/                 ← salidas de ejemplo (resúmenes, grafos)
├── docs/                           ← GitHub Pages (visor interactivo)
│   ├── index.html
│   ├── viewer.html
│   └── graphs/*.json
├── discourse_taxonomy.example.json
├── export_graph_web.py
├── publish_graphs.py
├── data/
│   ├── output/                   ← tu scrape (gitignored)
│   ├── analysis/                 ← tu análisis (gitignored)
│   └── raw/                      ← crudo instatouch (gitignored)
├── orchestrator.py
├── analyze.py
└── INSTRUCCIONES.md
```

