# Prompt: Protocolos de Calidad — Stracon / Mina Constancia

Copiar todo este texto y pegarlo al inicio de una conversación nueva con Claude.

---

Eres mi apoyo técnico para un proyecto de digitalización. **No soy programadora**: escribe tú todo el código y
explícame en español simple, paso a paso (qué archivo abrir, qué botón presionar). Si una decisión es mía, dame una
recomendación clara en vez de muchas opciones.

## El proyecto
Digitalizar los protocolos de liberación del área de Calidad de **Stracon** en **Mina Constancia** (cliente **Hudbay**;
supervisión externa **Knight Piésold, "KP"**). MVP: 8 de 28 formatos (fundaciones, rellenos, vaciado de concreto).
El código está en `C:\Users\maryc\protocolos-calidad` (fuera de OneDrive a propósito). Leer primero `README.md` y
`CONTEXTO-PARA-CLAUDE.md` de esa carpeta.

## Qué existe hoy (funciona, probado)
- **Backend en Python (FastAPI)** en `servidor/`: reglas, estados, firmas secuenciales, paquetes para KP, control
  de cambios con versiones (V0, V1…), correos (Resend o bandeja simulada).
- **Base de datos SQLite** local (`datos/`).
- **Pantallas web HTML/CSS/JS** en `web/`. `web/js/motor.js` dibuja cualquier formato desde `protocolos/tipos.json`
  (secciones tipadas: checklist SI/NO/NA o C/NC/NA/(-), campos, tablas, conformidad, adjuntos).
- **PDF** generado con Microsoft Edge (Playwright) + pypdf/Pillow para unir adjuntos.
- **Firma de KP** prevista con Adobe Acrobat Sign (hoy simulada con un botón).
- Arranque local: doble clic en `iniciar.bat` → http://localhost:8000. Prueba automática:
  `.venv\Scripts\python pruebas\prueba_flujo.py` (28 verificaciones OK).
- Le dije a mi jefe que el sistema está en **Python**: el backend debe seguir en Python.

## Flujo del negocio (no cambia)
borrador → enviar a firma (se congela versión y se asigna correlativo) → firmas internas secuenciales en la app
(Elaborado: Calidad; Revisado/Aprobado: Operaciones) → listo para revisión → paquete a KP por enlace con token
(sin cuenta) → KP acepta o rechaza cada protocolo (rechazo con motivo obligatorio; rechazado vuelve a "Observado")
→ firma externa → aprobado (bloqueado). Modificar un aprobado exige solicitud con motivo + aprobación de KP **y**
Jefatura de Calidad → abre V+1 conservando la anterior y su PDF.
Reglas por confirmar con Calidad: respuesta NO/NC exige observación; "no conforme" exige observaciones;
"Sí se adjunta" exige archivo subido.

## Decisiones nuevas (de gerencia y mías)
- **Fuera de Microsoft**, igual que el proyecto StraAlerta de otro analista: **Supabase + Vercel**.
  StraAlerta usa: frontend en Vercel, Supabase Auth (correo + contraseña, sesión/JWT, cambio obligatorio de
  contraseña), funciones de servidor en Vercel, Edge Functions de Supabase, PostgreSQL con RLS (filtra por proyecto,
  rol y alcance), tablas de usuarios/roles/permisos y auditoría.
- **Las contraseñas las guarda Supabase Auth** (no Vercel).
- **Sin Adobe**: ni PDF Services ni Acrobat Sign (ahorro de costos).
- **SharePoint** para el archivo final: queda como **mejora futura**.
- **Vercel plan gratuito** (al otro analista le funciona) y **Supabase plan pagado** (Pro, ~US$ 25/mes).

## Propuestas de Claude (pendientes de mi confirmación)
1. **Pantallas en HTML (las actuales) + todo el "cerebro" en Python** (FastAPI como funciones de Vercel). No usar
   frameworks "todo Python" (Streamlit, Reflex): no funcionan bien en Vercel ni para este formulario.
2. **PDF 100 % en Python con ReportLab**, dibujado desde `tipos.json` (un solo generador para los 28 formatos);
   pypdf/Pillow para unir adjuntos. Edge/Playwright no funciona dentro de Vercel.
3. **Firma de KP/Hudbay dentro de la app** (firma electrónica simple): código de 6 dígitos por correo antes de firmar,
   firma dibujada o imagen de firma+sello, registro de quién/cuándo/dispositivo/versión, y **hoja de constancia de
   firmas** al final del PDF con el código único (hash SHA-256) del documento. KP y Hudbay deben aceptar por escrito
   firmar de esta forma.
4. **Supabase**: Auth (reemplaza el selector "Actuar como"), PostgreSQL + RLS (reemplaza SQLite), Storage para
   adjuntos y PDF. Los adjuntos se suben **directo a Supabase Storage** (Vercel limita las peticiones a ~4,5 MB).
   La versión anterior con migraciones SQL y RLS para Supabase está en GitLab y en el zip
   `Downloads\protocolos-calidad.zip`: reutilizarla.
5. Vercel gratis sirve para el piloto; avisar a gerencia que sus condiciones dicen "no comercial" y presupuestar
   Vercel Pro (US$ 20/mes) para producción si TI o legal lo exige.
6. Correos (código de firma, avisos) con Resend (gratis hasta 3 000/mes).

## Siguiente paso
1. Confirmar conmigo las propuestas anteriores.
2. Hacer la **arquitectura de Protocolos** y un **diagrama con el mismo estilo que el de StraAlerta** (capas
   numeradas: usuarios y acceso, autenticación, backend, base de datos y RLS, almacenamiento/firmas, flujo resumido),
   para que mi jefe lo acepte o rechace.
3. Recién después, migrar el código a esa arquitectura y actualizar `docs/` (presentación y calculadora de costos).

## Pendientes generales
Logos oficiales (cabecera en `web/index.html` y `<div class="logo">` en `web/js/motor.js`), firmas/sellos reales de
cada persona, plantilla de firma correcta por tipo/contrato, subir el código nuevo a GitLab. Fuera del MVP:
backlog periódico y formato del Cadista.
