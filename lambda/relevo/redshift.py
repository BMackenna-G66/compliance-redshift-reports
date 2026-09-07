"""Paso 5: la conexión a Redshift, por la Data API.

**No hay host, ni puerto, ni contraseña.** El cluster tiene
`PubliclyAccessible: false` y su security group sólo acepta tráfico interno, así
que una conexión TCP clásica (psycopg2, DBeaver) no se establece nunca desde
afuera. La Data API de AWS es la vía que sí funciona: se habla con un endpoint
HTTPS de AWS con credenciales IAM, y el cluster nunca se expone.

Eso cambia la forma de fallar. No hay «connection refused» ni «timeout de red»:
hay `AccessDeniedException`, sesión SSO vencida, y consultas que quedan en
`STARTED` para siempre porque el cluster está pausado. `_diagnostico()` traduce
cada una a qué hacer.

Cuatro decisiones que valen la pena explicar:

  · **Sólo lectura, verificado en código.** El `DbUser` por defecto es
    `awsuser`, que es **superusuario del cluster**: puede borrar tablas de
    producción. Mientras se siga usando ese usuario, la única barrera real es
    esta: `_solo_lectura()` rechaza cualquier sentencia que no empiece en
    SELECT o WITH, y rechaza el `;` que permitiría encadenar una segunda.

  · **Parámetros, no interpolación.** La Data API acepta parámetros con nombre
    (`:valor`). El valor sale de un correo de un tercero: va como parámetro,
    jamás pegado al SQL. Un `int()` alrededor del valor también evitaría la
    inyección, pero sólo para enteros — y `cc_transaction_id` es texto.

  · **La Data API es asíncrona.** `execute_statement` devuelve un id y hay que
    preguntar por el estado. El timeout es nuestro, del lado del cliente, y por
    eso importa: sin él una consulta contra un cluster pausado cuelga la vuelta
    de la ingesta para siempre.

  · **Nombres de tres partes.** Los datos viven en el datashare `db_prod`, no en
    la base a la que uno se conecta (`dev`). Toda consulta tiene que decir
    `"db_prod"."esquema"."tabla"`. Es el error más común y da
    `Relation ... does not exist`.
"""
import os
import re
import time

REGION_POR_DEFECTO = "us-east-1"
CLUSTER_POR_DEFECTO = "compliance-redshift-cluster"
BASE_POR_DEFECTO = "dev"
DBUSER_POR_DEFECTO = "awsuser"
TIMEOUT_POR_DEFECTO = 60          # segundos por consulta, del lado del cliente


class ErrorRedshift(RuntimeError):
    """Cualquier falla de esta capa. Se atrapa arriba y se muestra al usuario."""


# --------------------------------------------------------------------------
# configuración

def config(entorno=None):
    """Lee la configuración del entorno.

    Las credenciales NO están acá: las resuelve boto3 por su cadena habitual
    (AWS_PROFILE con SSO en tu máquina, o AWS_ACCESS_KEY_ID en un servidor).
    Este módulo nunca las toca ni las registra.
    """
    e = entorno if entorno is not None else os.environ
    return {
        "cluster":   (e.get("REDSHIFT_CLUSTER") or CLUSTER_POR_DEFECTO).strip(),
        "workgroup": (e.get("REDSHIFT_WORKGROUP") or "").strip(),   # Redshift Serverless
        "base":      (e.get("REDSHIFT_BASE") or BASE_POR_DEFECTO).strip(),
        "dbuser":    (e.get("REDSHIFT_DBUSER") or DBUSER_POR_DEFECTO).strip(),
        "region":    (e.get("AWS_REGION") or e.get("AWS_DEFAULT_REGION") or REGION_POR_DEFECTO).strip(),
        "perfil":    (e.get("AWS_PROFILE") or "").strip(),
        "timeout":   int(e.get("REDSHIFT_TIMEOUT") or TIMEOUT_POR_DEFECTO),
    }


def faltantes(cfg):
    """Qué falta para poder consultar. Con la Data API casi nunca falta nada:
    el cluster y la base tienen default, y las credenciales las pone AWS."""
    faltan = []
    if not cfg.get("cluster") and not cfg.get("workgroup"):
        faltan.append("REDSHIFT_CLUSTER")
    if not cfg.get("base"):
        faltan.append("REDSHIFT_BASE")
    return faltan


def credenciales(entorno=None):
    """¿boto3 puede resolver credenciales AQUÍ Y AHORA? (identidad, sin consultar)

    Que exista el perfil no alcanza: una sesión SSO vencida existe igual y
    falla recién al usarla. Esto lo pregunta antes, y sin tocar el cluster.
    """
    e = entorno if entorno is not None else os.environ
    cfg = config(e)
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return False, "falta boto3: pip install boto3"
    try:
        s = boto3.Session(profile_name=cfg["perfil"] or None, region_name=cfg["region"])
        quien = s.client("sts").get_caller_identity()
        return True, quien.get("Arn", "")
    except (ClientError, BotoCoreError, Exception) as err:      # noqa: BLE001
        return False, _diagnostico(cfg, err)


def configurada(entorno=None):
    return not faltantes(config(entorno)) and credenciales(entorno)[0]


# --------------------------------------------------------------------------
# guarda de sólo lectura

_COMENTARIOS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_ESCRITURA = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|copy|unload|"
    r"vacuum|call|merge|replace)\b", re.I)


def _limpiar(sql):
    """Saca comentarios y espacio, para que la guarda mire SQL de verdad."""
    return _COMENTARIOS.sub(" ", sql or "").strip()


def _solo_lectura(sql):
    """Levanta si la sentencia no es una lectura simple. Devuelve el SQL limpio.

    No pretende ser un parser de SQL: es un cinturón contra el error humano en
    `consultas.json`. Pero con `awsuser` —superusuario— es lo único que separa
    un typo de un `DROP TABLE` en producción, así que no se saca.

    El `;` final se quita además porque la Data API lo rechaza.
    """
    limpio = _limpiar(sql)
    if not limpio:
        raise ErrorRedshift("consulta vacía")
    cuerpo = limpio.rstrip(";").rstrip()
    if ";" in cuerpo:
        raise ErrorRedshift("la consulta trae más de una sentencia (`;`): se rechaza")
    if not re.match(r"^\s*(select|with)\b", cuerpo, re.I):
        raise ErrorRedshift("la consulta no empieza en SELECT ni WITH: se rechaza")
    if _ESCRITURA.search(cuerpo):
        raise ErrorRedshift("la consulta contiene una palabra de escritura: se rechaza")
    return cuerpo


# --------------------------------------------------------------------------
# lectura de resultados

def _valor(celda):
    """Una celda de la Data API viene como {tipoValue: x} o {isNull: True}."""
    if celda.get("isNull"):
        return None
    for k, v in celda.items():
        if k != "isNull":
            return v
    return None


# --------------------------------------------------------------------------
# el cliente

class Redshift:
    """Cliente de la Data API. Perezoso: no arma nada hasta la primera consulta."""

    def __init__(self, cfg=None, entorno=None):
        self.cfg = cfg or config(entorno)
        self.api = None
        self.ultimo_error = ""

    # -- ciclo de vida --------------------------------------------------
    def cliente(self):
        if self.api is not None:
            return self.api
        faltan = faltantes(self.cfg)
        if faltan:
            raise ErrorRedshift("falta configurar: " + ", ".join(faltan))
        try:
            import boto3
        except ImportError as e:
            raise ErrorRedshift("falta boto3. Instalalo con:  pip install boto3") from e
        try:
            sesion = boto3.Session(profile_name=self.cfg["perfil"] or None,
                                   region_name=self.cfg["region"])
            self.api = sesion.client("redshift-data")
        except Exception as e:
            raise ErrorRedshift(_diagnostico(self.cfg, e)) from e
        return self.api

    def cerrar(self):
        """No hay conexión que cerrar: la Data API es HTTPS sin estado. Existe
        para que quien use esta clase no tenga que saberlo."""
        self.api = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    # -- consulta -------------------------------------------------------
    def _destino(self):
        """Cluster clásico o Serverless: la Data API los distingue por el campo."""
        if self.cfg.get("workgroup"):
            return {"WorkgroupName": self.cfg["workgroup"]}
        return {"ClusterIdentifier": self.cfg["cluster"], "DbUser": self.cfg["dbuser"]}

    def consultar(self, sql, params=None, timeout=None):
        """Ejecuta una lectura. Devuelve (columnas, filas, ms).

        `params` es {nombre: valor} y en el SQL se escribe `:nombre`. La Data API
        manda todo como texto, así que una columna numérica suele necesitar un
        cast explícito en el SQL (`= :valor::bigint`).
        """
        cuerpo = _solo_lectura(sql)
        api = self.cliente()
        seg = int(timeout or self.cfg.get("timeout") or TIMEOUT_POR_DEFECTO)
        t0 = time.time()

        kw = {"Database": self.cfg["base"], "Sql": cuerpo, **self._destino()}
        if params:
            kw["Parameters"] = [{"name": str(k), "value": str(v)} for k, v in params.items()]

        try:
            sid = api.execute_statement(**kw)["Id"]
        except Exception as e:
            self.ultimo_error = f"{type(e).__name__}: {e}"
            raise ErrorRedshift(_diagnostico(self.cfg, e)) from e

        # La Data API es asíncrona: se pregunta hasta que termine. El intervalo
        # arranca corto (la mayoría de estas consultas responden en <1s) y
        # crece, para no gastar llamadas en una consulta larga.
        limite, espera, d = t0 + seg, 0.15, None
        while time.time() < limite:
            try:
                d = api.describe_statement(Id=sid)
            except Exception as e:
                self.ultimo_error = f"{type(e).__name__}: {e}"
                raise ErrorRedshift(_diagnostico(self.cfg, e)) from e
            if d["Status"] in ("FINISHED", "FAILED", "ABORTED"):
                break
            time.sleep(espera)
            espera = min(espera * 1.6, 2.0)
        else:
            try:
                api.cancel_statement(Id=sid)      # no dejarla corriendo en el cluster
            except Exception:
                pass
            raise ErrorRedshift(
                f"la consulta superó {seg}s y se canceló. Si queda en STARTED para "
                f"siempre, el cluster `{self.cfg['cluster']}` puede estar pausado.")

        if d["Status"] != "FINISHED":
            msg = d.get("Error") or d["Status"]
            self.ultimo_error = msg
            raise ErrorRedshift(_error_sql(msg))
        if not d.get("HasResultSet"):
            return [], [], int((time.time() - t0) * 1000)

        columnas, filas, token = [], [], None
        while True:
            kw = {"Id": sid}
            if token:
                kw["NextToken"] = token
            try:
                res = api.get_statement_result(**kw)
            except Exception as e:
                self.ultimo_error = f"{type(e).__name__}: {e}"
                raise ErrorRedshift(_diagnostico(self.cfg, e)) from e
            if not columnas:
                columnas = [c["name"] for c in res["ColumnMetadata"]]
            filas.extend([_valor(c) for c in reg] for reg in res["Records"])
            token = res.get("NextToken")
            if not token:
                break
        return columnas, filas, int((time.time() - t0) * 1000)

    def dicts(self, sql, params=None, timeout=None):
        """Como `consultar`, pero devuelve (lista de dicts, ms)."""
        cols, filas, ms = self.consultar(sql, params, timeout)
        return [dict(zip(cols, f)) for f in filas], ms

    def salud(self):
        """Ping. Nunca levanta: devuelve el diagnóstico como dato."""
        cfg = dict(self.cfg)
        fuera = {"configurada": not faltantes(self.cfg), "faltan": faltantes(self.cfg),
                 "conexion": cfg, "via": "Data API", "ok": False, "error": "", "ms": 0}
        if fuera["faltan"]:
            fuera["error"] = "falta configurar: " + ", ".join(fuera["faltan"])
            return fuera
        hay, quien = credenciales()
        fuera["identidad"] = quien if hay else ""
        if not hay:
            fuera["error"] = quien
            return fuera
        try:
            _, filas, ms = self.consultar(
                "SELECT current_user AS usuario, current_database() AS base")
            fuera.update(ok=True, ms=ms,
                         usuario=str(filas[0][0]) if filas else "",
                         base=str(filas[0][1]) if filas else "")
        except ErrorRedshift as e:
            fuera["error"] = str(e)
        return fuera


# --------------------------------------------------------------------------
# diagnóstico

def _diagnostico(cfg, e):
    """Traduce el error de AWS a algo accionable.

    Los modos de falla de la Data API no se parecen a los de una conexión TCP:
    acá lo que se rompe son permisos y sesiones, no rutas de red.
    """
    t = f"{e}".lower()
    perfil = cfg.get("perfil") or "el perfil por defecto"
    if "getclustercredentials" in t:
        return ("falta el permiso `redshift:GetClusterCredentials`. Al usar DbUser, la "
                "Data API pide credenciales temporales en tu nombre y sin eso falla.")
    if "accessdenied" in t or "not authorized" in t:
        return (f"AWS rechazó la llamada con {perfil}: faltan permisos de "
                f"`redshift-data:*` (ExecuteStatement / DescribeStatement / "
                f"GetStatementResult) sobre `{cfg.get('cluster')}`.")
    if "expired" in t or "sso" in t or "token" in t:
        return f"la sesión venció. Corré:  aws sso login --profile {cfg.get('perfil') or '<perfil>'}"
    if "could not be found" in t or "profile" in t:
        return (f"no se encontró el perfil AWS `{cfg.get('perfil')}`. "
                f"Definí AWS_PROFILE, o dejá credenciales en el entorno.")
    if "unable to locate credentials" in t or "nocredentials" in t:
        return ("boto3 no encontró credenciales. En tu máquina: "
                "export AWS_PROFILE=compliance-admin. En un servidor: AWS_ACCESS_KEY_ID/SECRET.")
    if "clusternotfound" in t:
        return f"no existe el cluster `{cfg.get('cluster')}` en la región {cfg.get('region')}."
    if "endpointconnectionerror" in t or "could not connect" in t:
        return f"no se pudo llegar al endpoint de AWS en {cfg.get('region')}. ¿Hay salida a internet?"
    return f"{type(e).__name__}: {e}"


def _error_sql(msg):
    """El error viene del motor, no de AWS. La trampa clásica tiene nombre."""
    t = str(msg).lower()
    if "does not exist" in t and "relation" in t:
        return (f"{msg}\n  → Suele ser el nombre de tres partes: los datos viven en el "
                f"datashare `db_prod`, no en la base a la que te conectás. "
                f'Escribí "db_prod"."esquema"."tabla".')
    if "operator does not exist" in t or "cannot be cast" in t:
        return (f"{msg}\n  → La Data API manda los parámetros como texto. Si la columna "
                f"es numérica, castealo en el SQL: `= :valor::bigint`.")
    return str(msg)
