# Protocolos de Calidad — Stracon / Constancia (Hudbay)

MVP de digitalización de protocolos de liberación (fundaciones, rellenos y vaciado de concreto — 8 de 28 formatos).

**Arquitectura:** servidor en **Python** (FastAPI) + pantallas web (HTML/CSS/JavaScript).
**Sin Adobe:** los PDF se generan en Python (ReportLab + pypdf) y todas las firmas se hacen en el sistema
(personal Stracon con su sesión; KP / Hudbay con enlace personal + código al correo + firma dibujada).
Hoy la base de datos es SQLite local; el destino acordado es **Supabase** (inicio de sesión, PostgreSQL, archivos)
+ **Vercel** (publicación). SharePoint como archivo final queda como mejora futura.

```
iniciar.bat            ★ Doble clic: instala lo necesario (1ª vez), levanta el servidor y abre el navegador
requirements.txt       Librerías de Python
.env.ejemplo           Clave de correo (copiar como .env). Sin .env = modo demo (correos simulados)
servidor/              ★ Python
  main.py              Rutas de la API (/api/...) y entrega de las pantallas. Documentación: /docs
  logica.py            Flujo: estados, firmas, correlativos, paquetes para KP, Hoja de Cargo, cambios y versiones
  reglas.py            Validaciones del formulario (se repiten en el servidor: no se pueden saltar)
  pdf.py               PDF del protocolo, constancia de firmas y Hoja de Cargo (ReportLab); unión de adjuntos
  qc_index.py          QC Index en Excel (mismas hojas y columnas que el de Calidad + resumen mensual / ICRC)
  db.py                Base de datos (tablas, datos iniciales, maestros)
  correo.py            Correos (Resend) o bandeja simulada
  config.py            Rutas y claves (.env)
protocolos/
  tipos.json           Los 8 formatos: sigla del correlativo, secciones, ítems, conformidad, adjuntos y columnas del QC Index
  maestros.json        Desplegables: entregables → estructuras → planos (LP Ent y Est V1) y listas (turno, material…)
web/
  index.html           App interna (bandeja, editor, firmas, paquetes, QC Index, control de cambios, correos simulados)
  revision.html        Portal externo para KP / Hudbay (sin cuenta: enlace + código al correo + firma dibujada)
  js/motor.js          Motor único: dibuja cualquier formato desde su JSON, con desplegables en cascada
  js/datos.js          Conexión de las pantallas con el servidor Python
pruebas/prueba_flujo.py  Prueba automática del flujo completo (44 verificaciones)
datos/                 (se crea solo) base de datos, adjuntos y PDF. No se sube a GitLab
```

## Cómo usarlo

1. Doble clic en **`iniciar.bat`**. La primera vez tarda unos minutos (instala las librerías).
2. Se abre http://localhost:8000. Para apagar, cerrar la ventana negra.

Recorrido de la demo: Nuevo → elegir entregable / estructura / planos → llenar → Enviar a firma (se asigna
`ACR-RC-001`) → firmar (cambiando de usuario con "Actuar como") → Paquetes a revisión → Enviar paquete (se genera la
Hoja de Cargo) → **Correos (simulados)** → abrir el enlace como KP → aceptar / rechazar → "Enviar código" (llega a
Correos simulados) → firmar en el recuadro → Descargar PDF (con constancia) → **Descargar QC Index** →
Solicitar modificación → aprobar (Jefe de Calidad + KP con código) → V1.

Prueba automática (no toca los datos reales):
```bash
.venv\Scripts\python pruebas\prueba_flujo.py
```

## Reglas principales

- **Correlativo**: sigla del formato + código del entregable + número, por formato y entregable (`ATF-RC-001`,
  `ACR-TMF-001`…). N° de registro completo como en el QC Index: `ST.CA.PC.001.F002 [10203002] - ATF-RC-001`.
  Siglas: RT (topográfico, provisional), ATF, ACR, IPREVC, IPOSTVC, IS, ID (drenes, provisional), AITHC.
  Para pruebas empieza en 001; al pasar a producción se fija el número inicial de cada formato/entregable.
- **Desplegables**: Entregable → Estructura → Planos (varios por protocolo, filtrados por entregable) desde
  `protocolos/maestros.json`. Listas con sugerencias (material, equipo, tubería…) aceptan texto libre.
- **Validaciones** (confirmar con Calidad): NO / NC exige observación; "no conforme" exige observaciones;
  "Sí se adjunta" exige el archivo; entregable y estructura obligatorios y coherentes.
- **Firmas** secuenciales. Firma externa = enlace personal (vence a 15 días) + código de 6 dígitos al correo
  (vence a 10 min, 5 intentos, un solo uso) + firma dibujada. Se registra fecha/hora, IP y dispositivo.
- **PDF final** = formulario + adjuntos + hoja de **constancia de firmas** con código de verificación SHA-256.
- **Hoja de Cargo** (ST.CA.PG.001.F007) automática por paquete; KP la firma al registrar sus decisiones.
- **Versionado**: aprobado = bloqueado. Modificar exige motivo + aprobación de KP **y** Jefatura de Calidad → V+1;
  la versión anterior y su PDF firmado se conservan.

## Flujo de estados

```
borrador ─enviar─► firma_interna ─(firmas app)─► listo_revision ─paquete─► en_revision
   ▲                    │ rechazo                                         │ KP rechaza   │ KP acepta + firma
   │                    ▼                                                 ▼              ▼
   └──────────────── observado ◄──────────────────────────────────────────┘          aprobado
                                                                                         │ cambio aprobado
                                                                    en_modificacion (V+1) ◄┘
```

## Pendientes

- **Migrar a Supabase + Vercel** (en cuanto estén las cuentas): inicio de sesión (reemplaza "Actuar como"),
  PostgreSQL con RLS, Storage para adjuntos (subida directa, Vercel limita a ~4,5 MB por petición).
- Siglas definitivas de Topográfico y Drenes; número inicial de cada correlativo al salir a producción.
- Lista de planos de TMF y MIS; áreas de distribución de la Hoja de Cargo (columnas A…J).
- Usuarios reales, firmantes de KP/Hudbay, firmas y sellos escaneados (`datos/archivos/sellos/<id>.png`),
  logo oficial (`web/img/logo.png` para el PDF; cabecera en `web/index.html` y `web/js/motor.js`).
- Conformidad de KP y Hudbay para firmar en el sistema (firma electrónica simple).
- Maestro para editar preguntas y listas desde la app: **2ª etapa** (los formatos ya están versionados).
- Actualizar `docs/` (presentación y calculadora de costos) a la arquitectura actual.
