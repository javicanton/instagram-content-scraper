# Ejemplos del caso de estudio académico incluidos en el repositorio.
# Para tu propio proyecto: copia hashtags.example.csv → hashtags.csv
# y corpora.example.yaml → corpora.yaml

Este directorio contiene:

- `hashtags_*.csv` — listas de hashtags de ejemplo (investigación sobre discursos en Instagram).
- `analysis/<corpus>/` — salidas del pipeline de análisis (resúmenes, métricas, grafos GraphML).

Los CSV con texto literal de comentarios (`comments_enriched`, etc.) **no** se incluyen en el repositorio público por contener datos personales. Regenera el análisis localmente tras scrapear con tu sesión.

Para publicar grafos interactivos en GitHub Pages:

```bash
python publish_graphs.py
git add docs/graphs/
```
