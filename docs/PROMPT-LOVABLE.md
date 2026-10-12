# Prompt para Lovable — Protocolos de Calidad STRACON

Antes de pegar el prompt, sube a Lovable estas imágenes (están en `web/img/` del repositorio
`protocolos-calidad-api`): `logo.png`, `logo-negativo.png`, `isotipo.png`.
Copia todo lo que está debajo de la línea y pégalo en Lovable.

---

Crea el frontend de **"Protocolos de Calidad"**, una aplicación interna de **STRACON** (empresa de construcción y
minería) para digitalizar los protocolos de liberación del área de Control de Calidad en Mina Constancia
(cliente Hudbay; supervisión externa Knight Piésold, "KP"). Todo el texto de la interfaz va en **español**.

## Reglas de arquitectura (muy importante)
- **Solo frontend.** No crees base de datos, tablas, autenticación ni lógica de negocio propia, y no conectes Supabase
  por ahora. Toda la información viene de una **API REST en Python** ya construida (FastAPI).
- Crea una capa `src/api/` con una función por endpoint (ver lista abajo) y la URL base en `VITE_API_URL`.
  **Mientras la API no esté publicada, usa un modo simulado** (`VITE_API_MOCK=true`) con datos de ejemplo en
  memoria que respeten exactamente las formas JSON descritas aquí, para poder recorrer todo el flujo.
- El usuario actual se envía en el encabezado `X-Usuario: <id de perfil>`. Por ahora se elige con un selector
  "Actuar como" en la barra superior (lista de `GET /api/sesion` → `perfiles`). Más adelante se reemplazará por
  inicio de sesión real.
- **Los formularios NO se dibujan a mano.** Hay 8 formatos hoy y serán 28: crea UN componente
  `<FormularioProtocolo>` que renderice cualquier formato a partir de su definición JSON (`tipo.schema`, ver abajo).
  Agregar un formato nuevo nunca debe requerir una pantalla nueva.
- Uso en campo: debe funcionar muy bien en **tablet y celular** (botones de respuesta grandes, mínimo 44 px).

## Marca (Brandbook STRACON ST.MK.MA.001)
- Azul corporativo **#15284B** (principal: barra superior, títulos, botones primarios).
- Rojo corporativo **#F42534** (acento: detalles, estados de alerta, línea bajo la barra superior). No usarlo como fondo grande.
- Fondo blanco / gris muy claro. Tipografía: **Arial** (alternativa oficial a Haas Grot Disp); títulos en Arial Bold.
- Logo: `logo.png` sobre fondo blanco, `logo-negativo.png` sobre azul #15284B, `isotipo.png` para favicon y espacios chicos.
  No deformar, no cambiar colores, no sombras ni degradés. Dejar aire alrededor del logo.
- Estilo sobrio, corporativo e industrial; nada infantil.

## Pantallas

### App interna (personal Stracon)
1. **Bandeja de protocolos** (`/`): tabla con correlativo, formato, entregable/estructura, origen, versión, estado (chip de
   color) y fecha. Búsqueda y filtro por estado. Botón "Nuevo protocolo". Bloque "QC Index (Excel)" con selector de
   entregable y botón que descarga `GET /api/qc-index?entregable=<código>`.
2. **Nuevo** (`/nuevo`): selector de disparador ("Solicitud de Operaciones" / "Backlog") + tarjetas de los formatos
   (`GET /api/tipos`: código, nombre, categoría). Al elegir → `POST /api/protocolos` → abre el editor.
3. **Protocolo** (`/p/:id`): `GET /api/protocolos/:id`.
   - Si el estado es editable (`borrador`, `observado`, `en_modificacion`): formulario editable con **autoguardado**
     (PUT con 600 ms de espera, indicador "Guardando… / Guardado hh:mm"), botón "Validar" (lista de pendientes y
     resalta los campos) y "Enviar a firma" (diálogo para elegir firmantes por rol; ver abajo).
   - Si no: vista de solo lectura + botón "Descargar PDF" (`GET /api/protocolos/:id/pdf`).
   - Panel lateral: Firmas (rol, nombre, estado, fecha; botones Firmar / Rechazar con motivo cuando le toca al usuario
     actual), Adjuntos, Control de cambios, Versiones (con enlace al PDF de cada una), Historial.
   - Mostrar `numero_registro` (ej. `ST.CA.PC.002.F001 [10203002] - ACR-RC-001`) y la versión (V0, V1…).
4. **Paquetes a revisión** (`/paquetes`): protocolos `listo_revision` (`GET /api/protocolos?estado=listo_revision`)
   con casillas + selector de destinatario externo (contactos) + "Enviar paquete" (`POST /api/paquetes`).
   Debajo, paquetes enviados (`GET /api/paquetes`): código, aceptados/rechazados, enlace "Hoja de cargo"
   (`GET /api/paquetes/:id/hoja-cargo`) y, si viene `enlace_demo`, "Abrir como tercero (demo)".
5. **Correos (simulados)** (`/correos`, solo si `sesion.modo.demo`): lista de `GET /api/correos` (asunto, para, fecha y
   el HTML del cuerpo). Ahí llegan los enlaces y los códigos de firma en la demo.

### Portal externo para KP / Hudbay (`/revision?t=<token>`) — sin login, sin barra de la app interna
- `GET /api/revision/:token` → paquete, contacto (`correo` viene enmascarado), maestros e items.
- Por cada protocolo: correlativo, formato, estructura, enlace "Abrir PDF completo" (`pdf_url`), vista de solo lectura
  desplegable, y opción **Aceptar / Rechazar** (rechazo exige motivo).
- Enlace "Ver Hoja de Cargo" (`paquete.hoja_cargo_url`).
- Sección **"Firmar y enviar"**: recuadro para **firmar con el dedo o mouse** (canvas, botón Borrar; exportar PNG como
  data URL), botón "Enviar código a mi correo (<correo enmascarado>)" (`POST /api/revision/:token/codigo`, se puede
  reenviar tras 30 s), campo de **código de 6 dígitos**, y botón "Firmar y enviar decisiones"
  (`POST /api/revision/:token/decidir` con `{decisiones:[{instancia_id, decision:'aceptado'|'rechazado', motivo}], codigo, firma}`).
- Si `paquete.es_cambio` = true: pantalla de **solicitud de modificación** (motivo, cambios previstos, versión vigente),
  campo de código y botones Aprobar / Rechazar (`POST /api/revision/:token/cambio` con `{decision, motivo, codigo}`).

## Definición de un formato (`tipo.schema`) — lo que debe renderizar `<FormularioProtocolo>`
```json
{
  "secciones": [
    { "tipo": "checklist", "titulo": "Actividades", "opciones": "SI_NO_NA",
      "grupos": [ { "titulo": "Control de superficie", "items": [
        { "id": "c1", "texto": "Revisión de planos…", "ayuda": "texto opcional",
          "extra": { "label": "Espesor (mm)", "tipo": "number|text|lista", "lista": "material_relleno" } },
        { "id": "c4b", "texto": "Tipo de material", "solo_extra": true, "extra": { "label": "Tipo", "tipo": "lista", "lista": "material_relleno" } }
      ] } ] },
    { "tipo": "campos", "titulo": "Datos de la capa", "campos": [
      { "id": "capa_n", "label": "Capa N°", "requerido": true },
      { "id": "area", "label": "Área", "tipo": "number", "unidad": "m²" },
      { "id": "inicio_capa", "label": "Inicio de capa", "tipo": "datetime" },
      { "id": "turno", "label": "Turno", "tipo": "radio", "opciones": ["Día", "Noche"], "requerido": true },
      { "id": "fc", "label": "Resistencia f'c", "tipo": "select", "lista": "fc" },
      { "id": "equipo", "label": "Equipo", "tipo": "lista", "lista": "equipo_compactacion" } ] },
    { "tipo": "tabla", "id": "prestamo", "titulo": "Material de préstamo", "filas_min": 1, "filas_fijas": null,
      "columnas": [ { "id": "fase", "label": "Fase" }, { "id": "banco", "label": "Banco", "tipo": "select", "opciones": ["A","B"] } ],
      "nota": "texto opcional" }
  ],
  "conformidad": { "pregunta": "¿La capa de relleno se encuentra liberada?" },
  "adjuntos": [ { "id": "reporte_topografico", "label": "Reporte Topográfico", "tipo_adjunto": "topografia" } ]
}
```
- `opciones` del checklist: `SI_NO_NA` → SI / NO / N.A.; `C_NC_NA` → C / NC / NA / (-) con la leyenda
  "(-) No se requiere inspección · (C) Conforme · (NC) No conforme · (NA) No aplica". Columnas: Ítem (numerado, sin
  contar `solo_extra`), Descripción (+ campo `extra` debajo), una columna por opción (botones grandes; NO/NC en rojo),
  Observaciones.
- Tipos de campo: `text` (por defecto), `number`, `date`, `time`, `datetime`, `textarea`, `radio` (con `opciones`),
  `select` (opciones de `opciones` o de `maestros.listas[lista]`), `lista` (texto libre con sugerencias de
  `maestros.listas[lista]`). `unidad` se muestra al lado.
- `tabla`: filas fijas (`filas_fijas`, con etiqueta) o filas dinámicas con "+ Agregar fila" / quitar.
- Cierre: pregunta de `conformidad` (Sí/No) si existe; por cada adjunto "¿Se adjunta X?" Sí/NA + N° + subir archivo
  (`POST /api/protocolos/:id/adjuntos`, multipart: `archivo`, `tipo`, `ref_schema`); Observaciones; recuadros de firma
  (Elaborado por / Revisado-Aprobado por / Aceptado por) con imagen `sello_url`, nombre, cargo, empresa y fecha.
- **Cabecera fija** (igual para todos): Nombre del proyecto y Cliente (solo lectura), **Entregable** (desplegable de
  `maestros.entregables`), **Estructura** (desplegable que depende del entregable; si hay una sola, se elige sola),
  N° correlativo (solo lectura), Fecha, Elemento, **Plano ref.** (casillas múltiples con los planos del entregable +
  campo "Otro plano"), Descripción del trabajo. Al cambiar el entregable se limpian estructura y planos.
- Valor guardado (`PUT /api/protocolos/:id/valor`):
  `{cabecera:{entregable, estructura, fecha, elemento, plano_ref:[…], plano_otro}, respuestas:{checklist:{<id>:{r, obs, extra}}, campos:{<id>:valor}, tablas:{<id>:[{…}]}, adjuntos:{<id>:{adjunta:'SI'|'NA', numero}}, descripcion, observaciones}, conforme: true|false|null}`.
- Validación en pantalla (la API la repite): entregable, estructura y fecha obligatorios; campos `requerido`; todo ítem
  del checklist con respuesta; **NO / NC exige observación**; si "no conforme", Observaciones obligatorio; cada adjunto
  con respuesta; "Sí se adjunta" exige archivo subido.

## Diálogo "Enviar a firma"
Roles de `tipo.plantilla.roles` (`[{rol, empresa, area, canal:'app'|'externo'}]`). Para `canal:'app'` un desplegable
de perfiles (obligatorio; "Elaborado por" viene con el usuario actual); para `externo` un desplegable opcional de
contactos de esa empresa ("se asigna al armar el paquete"). Envía `POST /api/protocolos/:id/enviar-firma` con
`{firmantes:{<rol>:{perfil_id}|{contacto_id}}}`.

## Estados (chips)
`borrador` Borrador · `firma_interna` Firma interna · `listo_revision` Listo para revisión · `en_revision` En revisión
(tercero) · `aprobado` Aprobado (verde) · `observado` Observado (rojo) · `en_modificacion` En modificación · `anulado`.

## Endpoints (todas las rutas empiezan con `/api`)
| Método | Ruta | Uso |
|---|---|---|
| GET | `/sesion` | `{modo:{demo, correo_real}, perfiles, contactos}` |
| GET | `/tipos` | formatos con `schema` y `plantilla.roles` |
| GET | `/maestros` | `{proyecto, entregables:[{codigo, nombre, estructuras:[{codigo,nombre}], planos:[…]}], listas:{clave:[…]}}` |
| GET | `/protocolos?estado=` | bandeja |
| POST | `/protocolos` | `{tipo_id, origen, solicitud}` → `{id}` |
| GET | `/protocolos/:id` | `{inst, tipo, numero_registro, firmas, versiones, adjuntos, eventos, cambios}` |
| PUT | `/protocolos/:id/valor` | autoguardado |
| POST | `/protocolos/:id/adjuntos` | subir archivo (PDF/PNG/JPG) |
| GET / DELETE | `/adjuntos/:id` | ver / quitar adjunto |
| POST | `/protocolos/:id/enviar-firma` | congela versión y asigna correlativo |
| POST | `/firmas/:id/firmar` · `/firmas/:id/rechazar` (`{motivo}`) | firma interna |
| GET | `/protocolos/:id/pdf?version=` | PDF (se abre en pestaña nueva) |
| GET / POST | `/paquetes` | listar / crear `{instancias:[ids], contacto_id}` |
| GET | `/paquetes/:id/hoja-cargo` | PDF Hoja de Cargo |
| POST | `/protocolos/:id/cambios` | `{motivo, descripcion, contacto_id}` |
| POST | `/cambios/:id/decidir` | Jefatura: `{decision, motivo}` |
| GET | `/qc-index?entregable=` | Excel |
| GET | `/correos` | correos simulados (demo) |
| POST | `/reiniciar` | borrar datos de demo |
| GET | `/revision/:token` · POST `/revision/:token/codigo` · POST `/revision/:token/decidir` · POST `/revision/:token/cambio` | portal externo |

Errores: la API responde `{"error": "mensaje para el usuario"}` con código 4xx; mostrarlo en un aviso (toast).
La documentación completa e interactiva de la API está en `<VITE_API_URL>/docs`.
