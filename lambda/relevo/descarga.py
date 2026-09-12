"""Bajar todos los adjuntos de un caso de una sola vez.

Un caso con cinco archivos son cinco clics y cinco archivos sueltos en la
carpeta de descargas, sin nada que diga a qué caso pertenecen. Para revisar
documentación eso es justo la parte tediosa.

**Por qué devuelve un enlace y no el archivo.** El API Gateway tiene un tope
de respuesta de ~6 MB, y no hay forma de saber de antemano cuánto pesan los
adjuntos de un caso — un pasaporte escaneado a 600 dpi solo ya se acerca. Se
arma el zip, se sube a S3 y se devuelve una URL prefirmada: el navegador lo
baja directo del bucket y el tamaño deja de importar.

**Los zips son temporales, y eso hay que sostenerlo.** Son una copia de
documentos de identidad de clientes: dejarlos acumulándose en el bucket es
duplicar datos sensibles sin motivo. Viven bajo `relevo/descargas/`, el
enlace expira en 15 minutos, y cada corrida borra los que tengan más de una
hora. La limpieza es best-effort — si falla, se registra pero no rompe la
descarga, porque quedarse sin poder bajar los documentos es peor que un zip
viejo de más.
"""
import io
import os
import re
import time
import zipfile

from . import deposito

PREFIJO = os.environ.get("RELEVO_PREFIJO_DESCARGAS", "descargas")
SEGUNDOS_ENLACE = int(os.environ.get("RELEVO_ENLACE_SEGUNDOS", "900"))
# Cuánto puede vivir un zip antes de que la próxima corrida lo borre.
VIDA_ZIP = int(os.environ.get("RELEVO_VIDA_ZIP", "3600"))

_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def _nombre_zip(caso_id):
    """Un nombre que diga de qué caso es. El analista baja cinco archivos y
    tiene que poder decir a cuál pertenecen sin abrirlos."""
    base = _SEGURO.sub("-", str(caso_id or "caso")).strip("-")[:60] or "caso"
    return f"{base}-documentos.zip"


def _limpiar_viejos():
    """Borra los zips de corridas anteriores. No levanta nunca."""
    try:
        s3 = deposito._s3()
        pref = f"{deposito.PREFIJO}/{PREFIJO}/"
        corte = time.time() - VIDA_ZIP
        r = s3.list_objects_v2(Bucket=deposito.BUCKET, Prefix=pref, MaxKeys=1000)
        for o in r.get("Contents", []):
            if o["LastModified"].timestamp() < corte:
                s3.delete_object(Bucket=deposito.BUCKET, Key=o["Key"])
    except Exception as e:
        print(f"[relevo/descarga] no pude limpiar zips viejos: {e}")


def _unico(nombre, usados):
    """Dos adjuntos del mismo caso pueden llamarse igual —el cliente manda el
    mismo formulario dos veces— y en un zip el segundo pisa al primero."""
    if nombre not in usados:
        usados.add(nombre)
        return nombre
    raiz, punto, ext = nombre.rpartition(".")
    raiz = raiz or nombre
    for i in range(2, 100):
        cand = f"{raiz} ({i}){punto}{ext}" if punto else f"{nombre} ({i})"
        if cand not in usados:
            usados.add(cand)
            return cand
    usados.add(nombre)
    return nombre


def zip_de_caso(caso_id):
    """{url, nombre, archivos, bytes} o {error}. Arma, sube y prefirma."""
    if not deposito.activo():
        return {"error": "el depósito de S3 no está activo"}

    from . import devolucion
    adjuntos = devolucion.adjuntos_de(caso_id, con_enlace=False)
    if not adjuntos:
        return {"error": "el caso no tiene archivos recibidos"}

    s3 = deposito._s3()
    buf = io.BytesIO()
    dentro, fallidos, usados = [], [], set()
    # ZIP_DEFLATED y no ZIP_STORED: son PDF e imágenes, comprimen poco, pero
    # un zip sin comprimir del mismo tamaño que los originales confunde a
    # quien lo ve y no ahorra tiempo de CPU que importe acá.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a in adjuntos:
            clave = a.get("s3_key")
            if not clave:
                continue
            try:
                datos = s3.get_object(Bucket=deposito.BUCKET, Key=clave)["Body"].read()
            except Exception as e:
                # Un archivo ilegible no puede dejar sin zip a los otros
                # cuatro: se anota y se sigue.
                fallidos.append({"nombre": a.get("nombre"), "error": str(e)[:150]})
                continue
            nombre = _unico(str(a.get("nombre") or "adjunto"), usados)
            z.writestr(nombre, datos)
            dentro.append(nombre)

    if not dentro:
        return {"error": "no se pudo leer ninguno de los archivos",
                "fallidos": fallidos}

    cuerpo = buf.getvalue()
    clave = (f"{deposito.PREFIJO}/{PREFIJO}/"
             f"{deposito.clave_segura(caso_id)}-{int(time.time())}.zip")
    try:
        s3.put_object(Bucket=deposito.BUCKET, Key=clave, Body=cuerpo,
                      ContentType="application/zip")
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": deposito.BUCKET, "Key": clave,
                    "ResponseContentDisposition":
                        f'attachment; filename="{_nombre_zip(caso_id)}"'},
            ExpiresIn=SEGUNDOS_ENLACE)
    except Exception as e:
        return {"error": f"no pude preparar la descarga: {str(e)[:200]}"}

    _limpiar_viejos()
    return {
        "url": url,
        "nombre": _nombre_zip(caso_id),
        "archivos": dentro,
        "n": len(dentro),
        "bytes": len(cuerpo),
        "expira_en_segundos": SEGUNDOS_ENLACE,
        "fallidos": fallidos,
    }
