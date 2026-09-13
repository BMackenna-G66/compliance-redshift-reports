"""El trabajo de fondo: de un archivo del juzgado a los oficios de respuesta.

Corre en su propia Lambda (`compliance-embargos`), disparada async desde la
API. Vive aparte de la Lambda del portal por dos razones concretas:

  - **Dependencias.** `pdfplumber` + `docxtpl` + `ftfy` suman ~58 MB netos, y
    el paquete compartido ya está en 147 MB contra un límite de 250. Meterlas
    ahí encarece el arranque en frío de *todos* los endpoints por un módulo que
    se usa unas pocas veces al mes.
  - **Tiempo.** El portal corta a los 60 s y el API Gateway a los 30. Esto
    necesita minutos.

**Por tandas, con el estado en S3.** El plan estimaba 30-60 min para 15.000
Word; medido de verdad son 10 ms por documento, o sea ~2,4 min en una máquina
de escritorio. Entra en los 900 s de Lambda con margen, pero igual se procesa
por tandas por tres motivos que no dependen de esa medición:

  1. Un ZIP de 15.000 documentos son ~340 MB y la descarga se cae sola. En
     tandas quedan ZIP manejables.
  2. Da progreso real para mostrar en pantalla, no una barra inventada.
  3. Si la tanda no termina a tiempo —Lambda es más lenta que un portátil, y
     nadie sabe cuánto hasta medirlo allá— el trabajo se auto-invoca y sigue
     donde quedó, en vez de perder 10 minutos de trabajo.

**Nada de datos personales en los logs.** Lo pide el §10 de la documentación
del proceso y es Ley 1581: se registran conteos y el identificador de la
corrida, nunca un documento ni un nombre. Si hace falta depurar un registro
puntual, está en el Excel de resultados, que sí tiene control de acceso.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import boto3

s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")

BUCKET = os.environ.get("S3_BUCKET", "")
PREFIJO = os.environ.get("EMBARGOS_PREFIJO", "embargos")
YO = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "compliance-embargos")

# Cuántos oficios por ZIP. 500 × 23 KB ≈ 11 MB: se descarga sin drama.
POR_TANDA = int(os.environ.get("EMBARGOS_POR_TANDA", "500"))
# Margen antes del timeout para cerrar la tanda y auto-invocarse. Generar un
# documento son ~10 ms, pero subir el ZIP y guardar el estado no: 90 s alcanza
# para cerrar prolijo incluso si la tanda va lenta.
MARGEN_MS = int(os.environ.get("EMBARGOS_MARGEN_MS", "90000"))
# Tope de auto-invocaciones. Un bucle infinito acá es caro y silencioso.
MAX_TANDAS = int(os.environ.get("EMBARGOS_MAX_TANDAS", "80"))

ESTADOS = ("pendiente", "extrayendo", "validando", "generando", "listo", "error")


def _clave(run_id: str, *partes) -> str:
    return "/".join([PREFIJO, run_id, *partes])


def leer_estado(run_id: str) -> dict:
    try:
        o = s3.get_object(Bucket=BUCKET, Key=_clave(run_id, "estado.json"))
        return json.loads(o["Body"].read())
    except Exception:
        return {}


def guardar_estado(estado: dict) -> None:
    estado["actualizado_at"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    s3.put_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "estado.json"),
                  Body=json.dumps(estado, ensure_ascii=False, default=str).encode(),
                  ContentType="application/json")


def _marcar_error(estado: dict, e: Exception, etapa: str) -> dict:
    # El mensaje de la excepción puede arrastrar un fragmento de dato: se
    # recorta y se guarda sólo el tipo y los primeros caracteres.
    estado["estado"] = "error"
    estado["etapa"] = etapa
    estado["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    guardar_estado(estado)
    print(f"[embargos] run={estado['run_id']} etapa={etapa} FALLÓ: {type(e).__name__}")
    return estado


def _bajar(run_id: str, nombre: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(BUCKET, _clave(run_id, nombre), str(destino))
    return destino


def _subir(run_id: str, local: Path, nombre: str, tipo: str) -> str:
    clave = _clave(run_id, nombre)
    s3.upload_file(str(local), BUCKET, clave, ExtraArgs={"ContentType": tipo})
    return clave


def _plantillas() -> tuple:
    base = Path(__file__).resolve().parent / "plantillas"
    return (base / "Plantilla_Judicial_True_Client.docx",
            base / "Plantilla_Judicial_False_Client.docx")


def version_plantillas() -> str:
    """Huella de las dos plantillas juntas.

    El texto de estas plantillas es una declaración jurídica: hay que poder
    decir, meses después, con qué versión exacta se le respondió a un juzgado.
    Un hash del contenido no se puede olvidar de actualizar, a diferencia de un
    número de versión escrito a mano.
    """
    h = hashlib.sha256()
    for p in sorted(_plantillas()):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Las tres etapas
# ---------------------------------------------------------------------------

def _extraer(estado: dict, tmp: Path) -> dict:
    from . import extract

    origen = _bajar(estado["run_id"], estado["archivo_clave"],
                    tmp / estado["archivo_nombre"])
    r = extract.extraer(origen, estado.get("alias"))

    if estado.get("modo", "persona") == "persona":
        personas = extract.consolidar_por_persona(r.registros)
    else:
        personas = [x.to_dict() for x in r.registros]

    s3.put_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "personas.json"),
                  Body=json.dumps(personas, ensure_ascii=False, default=str).encode(),
                  ContentType="application/json")
    s3.put_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "descartados.json"),
                  Body=json.dumps([d for d in r.descartados], ensure_ascii=False,
                                  default=str).encode(),
                  ContentType="application/json")

    estado["conteos"] = {
        "filas": len(r.registros) + len(r.descartados),
        "validos": len(r.registros),
        "descartados": len(r.descartados),
        "personas": len(personas),
    }
    estado["etapa"] = "validando"
    print(f"[embargos] run={estado['run_id']} extraído: "
          f"{estado['conteos']['filas']} filas, {len(personas)} personas")
    return estado


def _validar(estado: dict) -> dict:
    from .redshift import ValidadorRedshift, marcar_clientes

    o = s3.get_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "personas.json"))
    personas = json.loads(o["Body"].read())

    v = ValidadorRedshift()
    marcar_clientes(personas, v)

    s3.put_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "personas.json"),
                  Body=json.dumps(personas, ensure_ascii=False, default=str).encode(),
                  ContentType="application/json")

    clientes = sum(1 for p in personas if p.get("es_cliente"))
    estado["conteos"]["clientes"] = clientes
    estado["conteos"]["no_clientes"] = len(personas) - clientes
    estado["consultas_redshift"] = v.consultas
    estado["etapa"] = "generando"
    estado["generados"] = 0
    estado["tandas"] = []
    print(f"[embargos] run={estado['run_id']} validado: {clientes} clientes "
          f"de {len(personas)} en {v.consultas} consultas")
    return estado


def _generar_tanda(estado: dict, tmp: Path, queda_ms) -> dict:
    """Genera hasta agotar personas o hasta quedarse sin tiempo."""
    from .docgen import construir_contexto, nombre_archivo
    from docxtpl import DocxTemplate

    o = s3.get_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "personas.json"))
    personas = json.loads(o["Body"].read())
    pc, pnc = _plantillas()
    fecha = None
    if estado.get("fecha"):
        try:
            fecha = dt.date.fromisoformat(estado["fecha"])
        except ValueError:
            fecha = None
    ciudad = estado.get("ciudad") or "Bogotá D.C."

    while estado["generados"] < len(personas):
        if queda_ms() < MARGEN_MS:
            print(f"[embargos] run={estado['run_id']} corto de tiempo, "
                  f"continúa en otra invocación ({estado['generados']}/{len(personas)})")
            return estado

        desde = estado["generados"]
        hasta = min(desde + POR_TANDA, len(personas))
        bloque = personas[desde:hasta]

        carpeta = tmp / f"t{desde}"
        carpeta.mkdir(parents=True, exist_ok=True)
        n_cli = 0
        for i, p in enumerate(bloque, start=desde + 1):
            es_cli = bool(p.get("es_cliente"))
            n_cli += es_cli
            doc = DocxTemplate(str(pc if es_cli else pnc))
            doc.render(construir_contexto(p, fecha=fecha, ciudad=ciudad))
            doc.save(carpeta / nombre_archivo(p, es_cli, i))

        # Un ZIP por tanda: 15.000 documentos en uno solo son ~340 MB y la
        # descarga se cae. Además así el analista ya puede bajar los primeros
        # mientras el resto se sigue generando.
        zp = tmp / f"oficios_{desde + 1}_{hasta}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(carpeta.iterdir()):
                z.write(f, f.name)
        clave = _subir(estado["run_id"], zp, f"oficios/{zp.name}", "application/zip")
        estado["tandas"].append({
            "desde": desde + 1, "hasta": hasta, "clave": clave,
            "bytes": zp.stat().st_size, "clientes": n_cli,
        })
        estado["generados"] = hasta
        guardar_estado(estado)

        # Se libera el disco enseguida: /tmp de Lambda es chico y 15.000
        # documentos son ~340 MB si se dejan acumular.
        shutil.rmtree(carpeta, ignore_errors=True)
        zp.unlink(missing_ok=True)
        print(f"[embargos] run={estado['run_id']} tanda {desde + 1}-{hasta} lista")

    return estado


def _cerrar(estado: dict, tmp: Path) -> dict:
    from .excel_out import escribir_excel

    o = s3.get_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "personas.json"))
    personas = json.loads(o["Body"].read())
    o = s3.get_object(Bucket=BUCKET, Key=_clave(estado["run_id"], "descartados.json"))
    descartados = json.loads(o["Body"].read())

    clientes = [p for p in personas if p.get("es_cliente")]
    no_clientes = [p for p in personas if not p.get("es_cliente")]
    c = estado.get("conteos", {})

    # La hoja Resumen es el respaldo de la corrida ante el juzgado y ante la
    # SFC: tiene que decir qué archivo se procesó, con qué criterio, cuántos
    # salieron de cada lado y con qué versión de plantilla se respondió.
    resumen = [
        {"indicador": "Identificador de la corrida", "valor": estado["run_id"]},
        {"indicador": "Archivo procesado", "valor": estado.get("archivo_nombre", "-")},
        {"indicador": "Huella del archivo (sha256)", "valor": estado.get("archivo_hash", "-")},
        {"indicador": "Ejecutado por", "valor": estado.get("solicitado_por", "-")},
        {"indicador": "Modo de generacion", "valor": estado.get("modo", "persona")},
        {"indicador": "Filas leidas", "valor": c.get("filas", 0)},
        {"indicador": "Registros validos", "valor": c.get("validos", 0)},
        {"indicador": "Registros descartados", "valor": c.get("descartados", 0)},
        {"indicador": "Personas unicas", "valor": c.get("personas", 0)},
        {"indicador": "Clientes Global66", "valor": len(clientes)},
        {"indicador": "No clientes", "valor": len(no_clientes)},
        {"indicador": "Consultas a Redshift", "valor": estado.get("consultas_redshift", 0)},
        {"indicador": "Version de plantillas", "valor": estado.get("version_plantillas", "-")},
        {"indicador": "Iniciado", "valor": estado.get("creado_at", "-")},
        {"indicador": "Terminado", "valor": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")},
    ]

    x = tmp / "resultado_validacion.xlsx"
    escribir_excel(x, clientes=clientes, no_clientes=no_clientes,
                   descartados=descartados, resumen=resumen)
    estado["excel_clave"] = _subir(
        estado["run_id"], x, "resultado_validacion.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    estado["estado"] = "listo"
    estado["etapa"] = "listo"
    estado["terminado_at"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[embargos] run={estado['run_id']} LISTO: "
          f"{estado['conteos'].get('clientes')} clientes, "
          f"{len(estado['tandas'])} tanda(s)")
    return estado


# ---------------------------------------------------------------------------

def ejecutar(evento: dict, contexto=None) -> dict:
    """Punto de entrada de la Lambda. Retoma desde donde haya quedado."""
    run_id = str(evento.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("falta run_id")

    def queda_ms():
        if contexto is None or not hasattr(contexto, "get_remaining_time_in_millis"):
            return 10 ** 9          # corriendo fuera de Lambda: sin límite
        return contexto.get_remaining_time_in_millis()

    estado = leer_estado(run_id)
    if not estado:
        raise ValueError(f"no hay estado para {run_id}")
    if estado.get("estado") == "listo":
        return estado

    estado["estado"] = "procesando"
    estado["intentos"] = int(estado.get("intentos", 0)) + 1
    if estado["intentos"] > MAX_TANDAS:
        return _marcar_error(estado, RuntimeError("demasiadas invocaciones"), "guardia")
    estado.setdefault("version_plantillas", version_plantillas())
    guardar_estado(estado)

    tmp = Path(tempfile.mkdtemp(dir="/tmp"))
    try:
        if estado.get("etapa") in (None, "", "pendiente", "extrayendo"):
            estado["etapa"] = "extrayendo"
            guardar_estado(estado)
            estado = _extraer(estado, tmp)
            guardar_estado(estado)

        if estado["etapa"] == "validando":
            estado = _validar(estado)
            guardar_estado(estado)

        if estado["etapa"] == "generando":
            estado = _generar_tanda(estado, tmp, queda_ms)
            o = s3.get_object(Bucket=BUCKET, Key=_clave(run_id, "personas.json"))
            total = len(json.loads(o["Body"].read()))
            if estado["generados"] < total:
                # Queda trabajo: se sigue en otra invocación. El estado ya está
                # en S3, así que la que entra retoma exactamente acá.
                guardar_estado(estado)
                lambda_client.invoke(FunctionName=YO, InvocationType="Event",
                                     Payload=json.dumps({"run_id": run_id}).encode())
                return estado
            estado["etapa"] = "cerrando"

        estado = _cerrar(estado, tmp)
        guardar_estado(estado)
        return estado

    except Exception as e:                                   # noqa: BLE001
        return _marcar_error(estado, e, estado.get("etapa", "?"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def previsualizar(evento: dict) -> dict:
    """Lee el archivo y devuelve qué entendió, SIN generar nada.

    Es la mitad que convierte esto en un proceso revisable. El plan lo pide
    así y tiene razón: extraer 35.000 filas toma 6 segundos, y ver el mapeo de
    columnas antes de confirmar es lo que evita descubrir que la columna del
    documento se leyó mal recién después de mandarle 15.000 oficios a un
    juzgado. La confirmación va en el medio, a propósito.

    Corre en esta Lambda y no en la del portal porque necesita `pdfplumber` y
    `openpyxl`, que pesan y no tienen por qué estar allá. El portal la invoca
    de forma síncrona: 6 s entran de sobra en los 30 s del API Gateway.
    """
    from . import extract

    run_id = str(evento.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("falta run_id")
    nombre = str(evento.get("archivo_nombre") or "archivo")

    tmp = Path(tempfile.mkdtemp(dir="/tmp"))
    try:
        origen = _bajar(run_id, evento.get("archivo_clave") or nombre, tmp / nombre)
        r = extract.extraer(origen, evento.get("alias"))
        rep = r.reporte

        personas = extract.consolidar_por_persona(r.registros)
        # Sólo las primeras filas: es una vista previa, y cada fila de más son
        # datos personales viajando sin necesidad.
        muestra = [{
            "documento": x.numero_documento,
            "documento_origen": x.numero_documento_raw,
            "tipo": x.tipo_documento,
            "nombre": x.nombre_completo,
            "oficio": x.numero_oficio,
            "proceso": x.numero_proceso,
            "monto": x.valor_limite_embargo,
            "hoja": x.hoja_origen,
            "fila": x.fila_origen,
            "alertas": [f for f in (x.flags or [])],
        } for x in r.registros[:10]]

        return {
            "run_id": run_id,
            "archivo": nombre,
            "formato": rep.formato,
            "hojas": rep.hojas,
            "hojas_omitidas": rep.hojas_omitidas,
            "conteos": {
                "filas": rep.filas_leidas,
                "validos": rep.registros_validos,
                "descartados": rep.registros_descartados,
                "personas": len(personas),
            },
            "metadatos": rep.metadatos_documento,
            # Las alertas de calidad se ven acá y no sólo en el Excel: son
            # justamente los registros que necesitan una decisión humana.
            "alertas": rep.conteo_flags,
            "motivos_descarte": rep.motivos_descarte,
            "muestra": muestra,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def lambda_handler(event, context):
    event = event or {}
    if event.get("accion") == "previsualizar":
        return previsualizar(event)
    return ejecutar(event, context)
