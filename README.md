# RC Air Spotter Automation

Automatización sin costo para alimentar el flujo editorial de **@rcairspotter** desde un álbum público de iCloud.

## Qué hace esta primera versión

1. Lee el álbum público de iCloud.
2. Detecta fotografías (ignora videos por ahora).
3. Mantiene un inventario persistente en `data/photos.json`.
4. Mantiene el registro de fotografías ya publicadas en `data/published.json`.
5. Genera una cola de candidatas en `data/queue.json`.
6. GitHub Actions ejecuta la sincronización una vez por día y guarda los cambios.

## Archivos

- `config.json`: configuración del álbum.
- `scripts/sync_icloud.py`: lector y sincronizador.
- `data/photos.json`: inventario.
- `data/published.json`: historial de publicaciones.
- `data/queue.json`: próximas candidatas.
- `.github/workflows/sync.yml`: automatización diaria.

## Importante

Las URLs directas que entrega iCloud son temporales. Por eso no se guardan permanentemente: se regenerarán cuando haga falta publicar.

Esta versión todavía **no publica sola en Instagram**. Primero valida que el inventario de iCloud sea estable. La segunda etapa conectará la cola con Metricool/ChatGPT.
