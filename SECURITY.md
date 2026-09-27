# Seguridad

## Reportar una vulnerabilidad

Si encontrás una vulnerabilidad, por favor **no abras un issue público**.
Reportala en privado desde la pestaña *Security* del repositorio
(*Report a vulnerability*). Respondo en cuanto pueda; es un proyecto
mantenido por una persona en su tiempo libre.

## Modelo de seguridad

OpenCaption Live está pensado para correr en la red de un evento, operado
por quien organiza. Lo que protege y lo que no:

| Qué | Cómo |
|---|---|
| Emitir audio (y consumir CPU o la key de Gemini) | Requiere `INGEST_TOKEN`, comparado en tiempo constante. |
| Meter audio en una sesión ajena | Una sesión admite un solo emisor. |
| Agotar memoria | Límites de sesiones, frames, cola de segmentos, historial y archivo. |
| Inyección en páginas | Todo el texto se muestra con `textContent`; CSP sin scripts inline. |
| Secretos en el repo | `.env` está en `.gitignore`; el token no viaja en URLs. |

**No protege** (por diseño):

- Ver subtítulos y exportar transcripciones es **público** para quien llegue
  al servidor. Para charlas privadas, usá un proxy con autenticación.
- No hay HTTPS propio: publicalo detrás de un proxy (ver README, *Publicarlo*).
- El contenido del audio llega a los modelos: alguien que hable al micrófono
  puede intentar manipular a un motor basado en LLM (Gemini u Ollama) para
  que muestre otro texto. Quien controla el micrófono controla los subtítulos.
