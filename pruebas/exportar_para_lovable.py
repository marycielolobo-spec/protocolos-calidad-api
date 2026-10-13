"""Exporta los datos reales de la API (formatos, maestros y usuarios de demo) para el modo simulado del frontend.

Uso:  .venv\\Scripts\\python pruebas\\exportar_para_lovable.py <ruta>\\src\\api\\datos-reales.ts
Volver a correrlo cada vez que cambien protocolos/tipos.json o protocolos/maestros.json.
"""
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PROTOCOLOS_DATOS"] = tempfile.mkdtemp(prefix="protocolos-export-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from servidor.main import app  # noqa: E402

if len(sys.argv) < 2:
    sys.exit("Indique el archivo de salida, p. ej. ..\\quality-standards-hub\\src\\api\\datos-reales.ts")

c = TestClient(app)
datos = {k: c.get(f"/api/{k}").json() for k in ("sesion", "tipos", "maestros")}
datos["sesion"]["modo"] = {"demo": True, "correo_real": False}

js = json.dumps(datos, ensure_ascii=False, indent=1)
salida = Path(sys.argv[1])
salida.write_text(
    "// GENERADO desde la API real (repositorio protocolos-calidad-api, pruebas/exportar_para_lovable.py).\n"
    "// No editar a mano: volver a exportar cuando cambien los formatos o los maestros.\n"
    "// Formas JSON de la API (no del frontend): pasan por src/api/adaptador.ts.\n"
    "/* eslint-disable */\n"
    f"export const DATOS_REALES: unknown = {js};\n", encoding="utf-8")
print(f"OK: {len(datos['tipos'])} formatos, {len(datos['maestros']['entregables'])} entregables -> {salida}")
