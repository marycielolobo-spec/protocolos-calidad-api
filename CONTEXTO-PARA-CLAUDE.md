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

## Pendientes de información (de Calidad)
Siglas de Topográfico y Drenes (hoy RT e ID provisionales), lista de planos por entregable (TMF, MIS), áreas de
distribución de la Hoja de Cargo, usuarios reales y firmantes externos, firmas/sellos escaneados, logo,
confirmar reglas NO/NC.

## Notas para trabajar aquí
- Formatos y maestros se cargan de `protocolos/*.json` al arrancar el servidor.
- Si cambian las tablas, subir `VERSION_ESQUEMA` en `servidor/db.py` (la base de prueba se respalda y se recrea).
- Tras cambios, correr `.venv\Scripts\python pruebas\prueba_flujo.py`.
- La usuaria no es programadora: explicar en español simple y paso a paso.
