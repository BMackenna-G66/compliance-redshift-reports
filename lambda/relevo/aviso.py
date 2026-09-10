"""Avisos a Slack: que alguien se entere cuando esto se rompe.

**Por qué hacía falta.** Cinco procesos corriendo cada 5-15 minutos y cero
alarmas en toda la cuenta. Si el token de Gmail caduca, si el `historyId` se
pierde —Gmail los retiene ~una semana y después devuelve 404— o si alguien
apaga un interruptor y se olvida, el síntoma es que la lista de casos deja de
crecer. Y eso **se ve exactamente igual que una semana tranquila**. El modo de
falla del módulo es el silencio, así que el aviso no es un lujo.

Dos clases de mensaje, a propósito:

    FALLA   → cuando un proceso revienta o devuelve error. Va en el momento.
    LATIDO  → una vez al día, con los conteos y **qué está apagado**. Va
              siempre, aunque esté todo bien: un canal donde sólo aparecen
              malas noticias es un canal que nadie sabe si funciona.

**Nunca levanta.** Un fallo mandando el aviso no puede tumbar el proceso que
lo estaba reportando; sería cambiar un problema por dos. Se registra en
CloudWatch y sigue.

Se replica el webhook de WatchTower en vez de importar su `post_slack` (§1:
réplica adaptada, no reuso): ese arma bloques de reporte que acá no aplican.
"""
import json
import os
import time
import urllib.error
import urllib.request

SECRETO = os.environ.get("SLACK_WEBHOOK_SECRET_ARN", "")
# Se puede silenciar sin desplegar, por si el canal se vuelve ruidoso.
ACTIVO = os.environ.get("RELEVO_AVISOS", "1").strip().lower() not in ("0", "false", "no")
_webhook = None


def _url():
    global _webhook
    if _webhook is None:
        if not SECRETO:
            _webhook = ""
        else:
            import boto3
            sm = boto3.client("secretsmanager",
                              region_name=os.environ.get("AWS_REGION", "us-east-1"))
            _webhook = (sm.get_secret_value(SecretId=SECRETO)
                        .get("SecretString", "") or "").strip()
    return _webhook


def _mandar(texto, bloques=None):
    """Devuelve (mandado, motivo). No levanta nunca."""
    if not ACTIVO:
        return False, "avisos desactivados (RELEVO_AVISOS=0)"
    try:
        url = _url()
    except Exception as e:
        print(f"[relevo/aviso] no pude leer el webhook: {e}")
        return False, str(e)[:200]
    if not url:
        return False, "no hay SLACK_WEBHOOK_SECRET_ARN configurado"

    cuerpo = {"text": texto}
    if bloques:
        cuerpo["blocks"] = bloques
    try:
        pedido = urllib.request.Request(
            url, data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(pedido, timeout=10) as r:
            r.read()
        return True, ""
    except Exception as e:
        # A propósito no se relanza: el aviso es secundario al proceso.
        print(f"[relevo/aviso] falló el envío a Slack: {e}")
        return False, str(e)[:200]


def falla(proceso, error, detalle=None):
    """Un proceso reventó. Va en el momento."""
    lineas = [f":rotating_light: *Relevo — falló `{proceso}`*",
              f"```{str(error)[:600]}```"]
    if detalle:
        lineas.append(f"_{str(detalle)[:300]}_")
    lineas.append(f"_{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_")
    return _mandar("\n".join(lineas))[0]


def _salud():
    """Los números del latido. Cada pieza en su try: que falte una no puede
    dejar sin mandar el aviso entero, que es justo cuando más se necesita."""
    d = {}
    try:
        from . import almacen
        d["mensajes"] = len(almacen.leer())
    except Exception as e:
        d["mensajes"] = f"error: {str(e)[:60]}"
    try:
        from . import vista
        _, meta = vista.completa()
        d["snapshot"] = meta.get("generado_en") or "nunca"
        d["transacciones"] = meta.get("n_transacciones")
        d["acciones"] = meta.get("n_acciones")
    except Exception as e:
        d["snapshot"] = f"error: {str(e)[:60]}"
    try:
        from . import estado as est
        d["history_id"] = est.leer("gmail_history_id")
    except Exception:
        pass
    return d


def latido():
    """El resumen diario. Sale aunque esté todo bien.

    Lo importante no son los conteos: es la línea de interruptores apagados.
    Un proceso apagado no produce ningún síntoma visible hasta que alguien
    pregunta por qué no entran casos, y para entonces pasaron días.
    """
    from . import interruptores as sw
    try:
        tablero = sw.estado()
    except Exception as e:
        tablero = {"procesos_apagados": [], "envio_activo": None,
                   "error": str(e)[:200]}
    s = _salud()

    lineas = ["*Relevo — resumen diario*",
              f"• {s.get('mensajes')} correos · {s.get('transacciones')} transacciones "
              f"· {s.get('acciones')} acciones registradas",
              f"• Último snapshot: {s.get('snapshot')}"]

    apagados = tablero.get("procesos_apagados") or []
    if apagados:
        lineas.append(f":warning: *Procesos APAGADOS: {', '.join(apagados)}* — "
                      f"nada va a entrar mientras sigan así")
    else:
        lineas.append("• Los cinco procesos están prendidos")

    lineas.append(f"• Envío al cliente: "
                  f"{'*ACTIVO*' if tablero.get('envio_activo') else 'apagado'}")

    otros = [c for c in (tablero.get("apagados") or []) if c not in apagados]
    if otros:
        lineas.append(f"• También apagados: {', '.join(otros)}")

    return _mandar("\n".join(lineas))[0]
