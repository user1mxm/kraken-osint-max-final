# KRAKEN OSINT MAX vFinal

Plataforma OSINT/SOCINT con utilidades locales para analizar datasets ya obtenidos.

## Capacidades actuales

- SOCINT: extracción de cuentas, menciones, hashtags, dominios, correos y teléfonos.
- SOCMINT: agregación por cuenta, actividad por hora y patrones básicos de interacción.
- Scraped sources: resumen de dominios, plataformas y URLs detectadas.
- Leaks y breaches: detección de indicadores de credenciales, tokens, tarjetas y PII expuesta.
- Sentiment analysis: clasificación positiva, neutral o negativa por registro.
- Graphs: generación de nodos y relaciones en JSON y Mermaid.

## Uso rápido

Analizar un archivo JSON o texto plano:

```bash
python /home/runner/work/kraken-osint-max-final/kraken-osint-max-final/kraken_scrape_hub.py INPUT.json -o analysis.json
```

Mostrar solo el grafo Mermaid:

```bash
python /home/runner/work/kraken-osint-max-final/kraken-osint-max-final/kraken_scrape_hub.py INPUT.json --graph-format mermaid
```

## Formatos de entrada soportados

- JSON con listas o diccionarios que incluyan campos como `text`, `content`, `body`, `author`, `username`, `platform`, `url` o `timestamp`.
- Texto plano con una observación por línea.

## Despliegue rápido

```bash
docker compose up -d
```