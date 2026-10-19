# Contexto del proyecto (traspaso entre sesiones de Claude)

Leer esto antes de trabajar. Resume lo hecho y lo decidido hasta el 12 de octubre de 2026.

## Qué es
Digitalización de protocolos de liberación del área de Calidad de Stracon en Mina Constancia (cliente Hudbay;
supervisión externa Knight Piésold, "KP"). MVP: 8 de 28 formatos. Detalle técnico en `README.md`.
Ubicación: `C:\Users\maryc\protocolos-calidad` (fuera de OneDrive a propósito: el `.venv` no debe sincronizarse).
La subcarpeta `protocolos-calidad\` dentro del proyecto es una copia vieja (Supabase/Deno): ignorarla.

## Decisiones (gerencia + usuaria)
- Backend en **Python** (la usuaria se lo comprometió a su jefe). Pantallas en HTML/JS.
- Entorno **fuera de Microsoft**, como el proyecto StraAlerta: **Supabase** (pagado: Auth, PostgreSQL+RLS, Storage)
  + **Vercel** (gratis por ahora; avisado que su plan gratis es "no comercial").
- **Sin Adobe**: PDF con ReportLab; firmas de KP/Hudbay en la app (enlace + código al correo + firma dibujada +
  constancia con SHA-256). Falta que KP/Hudbay acepten por escrito este tipo de firma.
- SharePoint como archivo final: mejora futura. Maestro de preguntas: 2ª etapa.
- Hoja de Cargo (ST.CA.PG.001.F007): la exige el Jefe de Calidad → se genera sola por paquete.
- QC Index: se genera en Excel desde el sistema.
- Correlativos: `SIGLA-ENTREGABLE-NNN` (p. ej. ACR-RC-097). Para pruebas desde 001; el número inicial real se fija
  al pasar a producción.

## Estado (12 oct 2026)
- Hecho y probado (`pruebas/prueba_flujo.py`: 44 verificaciones OK; recorrido en navegador OK; PDF revisados):
  maestros y desplegables en cascada (`protocolos/maestros.json`), formatos ajustados a los registros reales
  REG/RTF (stage, fase/banco/polígono, inicio/fin de capa, RT N°, turno…), correlativo nuevo, PDF ReportLab,
  firma externa con código, constancia, Hoja de Cargo, QC Index.
- Aún en SQLite local con selector "Actuar como". **Siguiente paso: migrar a Supabase + Vercel** cuando la usuaria
  entregue los accesos (pedirle que pegue las claves en `.env`, nunca en el chat, sobre todo la `service_role`).
- Fuentes recibidas: QC INDEX RC.xlsx, LP Ent y Est V1.xlsx, REG 133/134 (Capa de Relleno TMF Este),
  RTF 23/24 (Terreno de Fundación TMF Oeste), ST.CA.PG.001.F007 (Hoja de Cargo) — en Descargas de la usuaria.

## Repositorios (GitHub, cuenta marycielolobo-spec)
- API Python: `protocolos-calidad-api` → carpeta `C:\Users\maryc\protocolos-calidad`.
- Pantallas (Lovable, React/TanStack Start): `quality-standards-hub` → copia local `C:\Users\maryc\quality-standards-hub`.
  Lovable sincroniza con GitHub: no reescribir historia (sin force push). `src/api/adaptador.ts` traduce API ↔ pantallas;
  `src/api/datos-reales.ts` se regenera con `pruebas/exportar_para_lovable.py`. Modo simulado si no hay `VITE_API_URL`.
  Probado de punta a punta contra la API real (13 oct 2026). El puerto 5173 de la PC está ocupado por otro programa.
- Correo: Microsoft 365 rechaza SMTP con contraseña (535 5.7.3) para datos.constancia@stracon.com → usar Gmail del
  sistema (la usuaria pedirá un chip corporativo para la verificación en 2 pasos). TI no verifica dominio para Resend.

## Estado al 16 oct 2026 — Supabase conectado
- La API usa Supabase si .env tiene DATABASE_URL + SUPABASE_URL + claves (proyecto hwljayjibfakzvznjtih, São Paulo):
  PostgreSQL con RLS en las 20 tablas (clave publicable no lee nada), Storage privado (bucket "protocolos"),
  Supabase Auth (correo + contraseña, alta por admin con clave temporal y cambio obligatorio). Sin .env → SQLite local + "Actuar como".
- Cargados: 19 usuarios Stracon (roles PROVISIONALES por cargo; admins Eduardo Urteaga y Josemir Paredes) y 10 externos
  (6 Hudbay, 4 KP) con herramientas/cargar_usuarios.py. Sus contraseñas son aleatorias: dar acceso = "Contraseña temporal" en /usuarios.
- Falta la cuenta de administradora de la usuaria (pedir su correo) y publicar en Vercel.
- Modificación de un aprobado (corrección de la usuaria, 16 oct): Calidad solicita → valida la Jefatura de Calidad
  (solo jefe_calidad) → recién entonces se envía a KP, que es quien aprueba al final → V+1 "en_modificacion".
- Reunión con Calidad (16 oct): flujo nuevo = supervisor llena → "Firmar y enviar" (firma "Elaborado por" al enviar)
  → estado validacion_doc → analista de Control Documentario (rol control_documentario, son 2; NO firma, solo valida
  con lista de verificación; si observa vuelve al supervisor y al reenviar regresa al analista) → Operaciones firma
  → paquete. Pantalla /validacion (tabla + revisión automática + lista CHECKS_DOC en logica.py; no tenían Excel
  propio: la lista es propuesta nuestra, ajustable). KP/Hudbay: "Confirmar recepción" firma la Hoja de Cargo al
  recibir (/api/revision/{t}/recepcion); decide después. Pueden firmar con imagen cargada/guardada (sellos/contactos/).
- Topografía (17 oct, servidor/topografia.py, pantalla /topografia): el cadista (rol "topografia") hace el Reporte
  Topográfico (correlativo propio 001; actividades fijas; equipo del Excel EME → tabla equipo; georreferencia fija en
  meta; CSV punto,norte,este,elev máx 16; plano obligatorio unido en el mismo PDF) → un supervisor de Calidad lo valida
  (firma "Revisado") u observa → "disponible" → se une 1 a 1 a un protocolo (instancia.vinculado_a) → KP lo firma con
  el protocolo; va en la Hoja de Cargo. Config admin: Excel anual de equipos, topógrafos (tabla topografo), georreferencia.
- Geoceldas ST.CA.PC.011.F001 (AIGC) cargado. Correlativos: TMF sin código (ATF-001), RC/WRF con código. Entregable WRF
  sin planos aún. MIS se queda por ahora. Firma "Elaborado por" muestra la fecha del protocolo (constancia: hora real).
- Roles (19 oct): cadista (hace el reporte topográfico: Pamela Choque, Luis Ramos, Luis Medrano) ≠ topografia (consulta:
  Juan Colquehuanca, jefe, y Marcos Reyes); consulta = solo lectura (Rodolfo Jove). cargar_usuarios usa la columna
  "Cargo en el sistema". Planos TMF (30) y WRF (10) cargados; MIS sin planos.
- Dossier (servidor/dossier.py, pantalla /dossier): filtros entregable + tipos + periodo (mes, rango, todo); solo
  aprobados; PDF carátula+índice+separador por tipo+protocolos; QC Index con los mismos filtros; envío al cliente con
  Hoja de Cargo y acuse. QC Index con el encabezado de la plantilla (disciplina por formato en tipos.json).
- PENDIENTE: georreferencia por entregable (el residente dice que cambia; Juan Colquehuanca validará la lista de BM).
  Contratos: hoy uno solo (10203002); la usuaria buscará los demás.
- Pruebas: pruebas/prueba_flujo.py (108, local) y prueba_supabase.py (20) y pruebas/prueba_supabase.py (19, contra Supabase real; borra lo que crea).
- Lovable (quality-standards-hub): /ingresar, /cambiar-clave, /usuarios, /mi-firma; client.ts maneja token y renovación.
- Las pantallas HTML de web/ son la demo vieja: con Supabase en .env no tienen login. Las pantallas oficiales son las de Lovable.

## Pendientes de información (de Calidad)
Siglas de Topográfico y Drenes (hoy RT e ID provisionales), lista de planos por entregable (TMF, MIS), áreas de
distribución de la Hoja de Cargo, usuarios reales y firmantes externos, firmas/sellos escaneados, logo,
confirmar reglas NO/NC.

## Notas para trabajar aquí
- Formatos y maestros se cargan de `protocolos/*.json` al arrancar el servidor.
- Si cambian las tablas, subir `VERSION_ESQUEMA` en `servidor/db.py` (la base de prueba se respalda y se recrea).
- Tras cambios, correr `.venv\Scripts\python pruebas\prueba_flujo.py`.
- La usuaria no es programadora: explicar en español simple y paso a paso.
