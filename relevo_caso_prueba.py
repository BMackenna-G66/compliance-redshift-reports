#!/usr/bin/env python3
"""Casos de prueba desechables para iterar sobre el ciclo RFI.

    python3 relevo_caso_prueba.py crear --correo tu@gmail.com
    python3 relevo_caso_prueba.py crear --variante empresa --correo tu@gmail.com
    python3 relevo_caso_prueba.py listar
    python3 relevo_caso_prueba.py borrar --todos

**Para qué.** Probar el ciclo completo —pedido, respuesta del cliente,
checklist, devolución— exige un caso cuyo cliente sea una casilla tuya. Los
casos reales apuntan a clientes reales, y usarlos para probar deja marcado
como "pedido enviado" algo que el cliente nunca recibió. Esto fabrica casos
que se pueden romper sin consecuencias.

**Cómo funciona.** Inyecta dos objetos en el depósito: un correo sintético
con la forma exacta de un RFI real —para que el motor lo parsee de verdad, no
para saltearlo— y la resolución del cliente ya hecha, apuntando a tu correo.
El resto del ciclo es el de producción, sin atajos: el mismo motor, el mismo
envío, el mismo poller.

**Cada caso queda anotado en `relevo/pruebas/`**, que es lo que permite
listarlos y borrarlos sin adivinar. Sin ese registro habría que reconocerlos
por el id, y un caso de prueba olvidado entre los reales es peor que no tener
la herramienta: ensucia los conteos y alguien termina trabajándolo en serio.

**No toca casos reales.** `borrar` sólo mira el registro; si un id no está
ahí, no lo borra.
"""
import argparse
import hashlib
import json
import os
import re
import time

import boto3

BUCKET = os.environ.get("RELEVO_BUCKET",
                        "compliance-redshift-reports-561521480266-us-east-1")
PREFIJO = os.environ.get("RELEVO_PREFIJO", "relevo")
REGION = os.environ.get("AWS_REGION", "us-east-1")
# Rango reservado dentro del válido de `rmt` (1.000.000–40.000.000). Alto a
# propósito: los reales rondan los 28M, así que 39.99x.xxx no colisiona.
BASE_RMT = 39990000

# Cada partner tiene su llave, su remitente y su forma de correo. Son datos
# reales de reglas.json y de correos ya ingeridos: un caso de prueba que el
# motor no reconozca no prueba nada.
PARTNERS = {
    "dlocal": {
        "nombre": "dLocal", "llave": "rmt", "base": BASE_RMT,
        "remitente": "no_reply@dlocal.com",
        "display": "\"'d·Local' via Compliance\" <compliance@global66.com>",
        "asunto": "New RFI is requested - RMT0{id}",
        "caso_id": "dlocal:rmt:{id}",
    },
    "currencycloud": {
        # `cc_transaction_id`, NO `cc_external_id`: ese último es la llave que
        # no sabemos componer y sus 16 casos quedan sin resolver. Un caso de
        # prueba tiene que ejercitar el camino que funciona.
        "nombre": "Currencycloud", "llave": "cc_transaction_id",
        "remitente": "kycrequests@currencycloud.com",
        "display": "\"Currencycloud via Compliance\" <compliance@global66.com>",
        "asunto": "[Currencycloud] - {tic} - Compliance Query - {nombre}",
        "caso_id": "currencycloud:caso:{tic}",
    },
}

_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")
s3 = boto3.client("s3", region_name=REGION)


def clave_segura(valor):
    b = str(valor or "")
    legible = _SEGURO.sub("_", b).strip("_")[:60] or "x"
    return f"{legible}-{hashlib.sha256(b.encode()).hexdigest()[:12]}"


def _ruta(col, clave):
    return f"{PREFIJO}/{col}/{clave}.json"


def poner(col, clave, dato):
    s3.put_object(Bucket=BUCKET, Key=_ruta(col, clave),
                  Body=json.dumps(dato, ensure_ascii=False).encode("utf-8"),
                  ContentType="application/json")
    return _ruta(col, clave)


def todos(col):
    fuera, token = [], None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": f"{PREFIJO}/{col}/", "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            if o["Key"].endswith(".json"):
                fuera.append(o["Key"])
        token = r.get("NextContinuationToken")
        if not token:
            return fuera


# ── las variantes ────────────────────────────────────────────────────────
# Cada una ejercita un camino distinto del ciclo. El cuerpo imita la forma
# real de un RFI de dLocal (verificado contra correos ingeridos) para que el
# motor tenga que extraer de verdad.
VARIANTES = {
    "completo": {
        "que": "persona, 3 documentos del catálogo — el camino feliz",
        "nombre": "Benjamin Mackenna",
        "pedidos": ["- Source of funds", "- Purpose of the payment",
                    "- Relationship between the sender and the beneficiary"],
    },
    "empresa": {
        "que": "razón social — verifica el trato de usted y plural",
        "nombre": "MACKENNA SOLUCIONES SPA",
        "pedidos": ["- Source of funds", "- Nature of business", "- Website"],
    },
    "sin_items": {
        "que": "el partner no dice qué pide — debe quedar en sin_requerimiento "
               "y NO dejarse enviar",
        "nombre": "Benjamin Mackenna",
        "pedidos": [],
    },
    "uno_solo": {
        "que": "un solo documento — el más rápido para probar ida y vuelta",
        "nombre": "Benjamin Mackenna",
        "pedidos": ["- Source of funds"],
    },
}


def _cuerpo_dlocal(ident, nombre, pedidos):
    lineas = [
        "d•local", "Dear Global 66 - XB,",
        "We would like to advise that we have received a payout request for the "
        "transaction below:",
        "Country\tCL",
        f"Beneficiary Last Name\t{nombre.split()[-1]}\tAmount\tUSD 1234",
        f"Beneficiary Name\t{nombre.split()[0]}\tPayout ID\t9{ident}",
        f"External ID\tRMT0{ident}",
    ]
    if pedidos:
        lineas.append("According to our Payments Policy and International Compliance "
                      "Standards, there are certain circumstances where we require "
                      "additional information.")
        lineas.append("Supporting documentation required to continue processing payouts:")
        lineas += pedidos
    lineas.append("Sent by dLocal , payment service provider for Global 66 - XB.")
    return "\n".join(lineas)


def _cuerpo_currencycloud(ident, nombre, pedidos, tic):
    """La forma real de un RFI de Currencycloud: hilo de Zendesk, el pedido en
    prosa y la firma de un analista. Copiado de correos ya ingeridos."""
    lineas = [
        "##- Please type your reply above this line -##",
        f"Your request ({tic}) has been updated. To add additional comments, "
        "reply to this email.",
        "----------------------------------------------",
        "James Patrick Tadioan, 10 Sept 2026, 18:03 BST",
        "Hi Team,",
        "We are conducting a routine review of the transaction below and require "
        "further information before it can be released.",
        f"Transaction ID: {ident}",
        f"Beneficiary: {nombre}",
        "Amount: USD 2,480.00",
    ]
    if pedidos:
        lineas.append("Please provide the following:")
        lineas += pedidos
        lineas.append("If you require more time, please reply to this query and we "
                      "may be able to offer an extension.")
    lineas += [
        "Kind regards,", "James Patrick Tadioan", "Associate Analyst",
        "Real-Time Transaction Monitoring Team,", "Currencycloud Compliance",
        "----------------------------------------------",
    ]
    return "\n".join(lineas)


def crear(a):
    v = VARIANTES[a.variante]
    P = PARTNERS[a.partner]
    nombre = a.nombre or v["nombre"]
    # El identificador tiene la forma que la regla de extracción exige. Con
    # cualquier otra el motor no la encuentra, no hay transacción y no hay
    # caso: el fixture tiene que hablar el idioma del partner.
    if a.partner == "currencycloud":
        # cc_transaction_id: IF-AAAAMMDD-XXXXXX  (patrón IF-\d{8}-[A-Z0-9]{5,8})
        import random
        import string
        ident = (time.strftime("IF-%Y%m%d-", time.gmtime())
                 + "".join(random.choices(string.ascii_uppercase + string.digits, k=6)))
    else:
        ident = str(P["base"] + int(time.time()) % 9999)
    tic = str(1400000 + int(time.time()) % 9999)          # nº de ticket del partner
    caso_id = P["caso_id"].format(id=ident, tic=tic)
    mid = f"PRUEBA-{a.partner}-{ident}"

    if a.partner == "currencycloud":
        cuerpo = _cuerpo_currencycloud(ident, nombre, v["pedidos"], tic)
        asunto = P["asunto"].format(tic=tic, nombre=nombre)
        llave_cache = f'{P["llave"]}|{ident}'
    else:
        cuerpo = _cuerpo_dlocal(ident, nombre, v["pedidos"])
        asunto = P["asunto"].format(id=ident)
        llave_cache = f'{P["llave"]}|{ident}'

    poner("mensajes", clave_segura(mid), {
        "id": mid, "thread_id": mid, "asunto": asunto, "cuerpo": cuerpo,
        "headers": {
            "From": P["display"],
            "To": "compliance@global66.com",
            "X-Original-Sender": P["remitente"],
            "Reply-To": P["remitente"],
            "Subject": asunto,
            "Date": time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime()),
            "Message-ID": f"<{mid}@prueba.local>",
            "List-ID": "<compliance.global66.com>",
            "X-Relevo-Prueba": "relevo_caso_prueba.py",
        },
        "texto_adjuntos": [], "esperado": None,
        "fecha": str(int(time.time() * 1000)), "_prueba": True,
    })

    poner("clientes", clave_segura(llave_cache), {
        "llave": P["llave"], "valor": ident, "estado": "encontrado",
        "motivo": "CASO DE PRUEBA — resolución inyectada, no salió de Redshift",
        "cliente": {
            "cliente_id": 999000000 + (abs(hash(ident)) % 1000),
            "cliente_nombre": nombre, "cliente_correo": a.correo,
            "cliente_pais": "Chile",
            "tx_monto": "2480.00", "tx_moneda": "USD",
            "tx_fecha": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "tx_estado": "PRUEBA",
            "tx_beneficiario": nombre, "tx_remitente": nombre,
            "extra": {"ref_nuestra": str(ident), "_prueba": True},
        },
        "verificacion": {}, "filas": 1, "ms": 0,
        "cuando": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "_prueba": True,
    })

    poner("pruebas", clave_segura(caso_id), {
        "caso_id": caso_id, "rmt": ident, "ident": ident, "llave": P["llave"],
        "partner": a.partner, "message_id": mid,
        "variante": a.variante, "correo": a.correo, "nombre": nombre,
        "creado": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    })

    print(f"\n  Caso creado: {caso_id}")
    print(f"    partner  : {P['nombre']}  ({P['llave']} = {ident})")
    print(f"    variante : {a.variante} — {v['que']}")
    print(f"    cliente  : {nombre} <{a.correo}>")
    print(f"    documentos que va a pedir: {len(v['pedidos'])}")
    print("\n  Falta que el snapshot lo levante (corre solo cada 5 min). Para ya:")
    print("    aws lambda invoke --function-name compliance-redshift-reports \\")
    print("      --payload '{\"report_name\":\"relevo_vista\"}' --cli-binary-format "
          "raw-in-base64-out /dev/stdout --profile compliance-admin\n")


def listar(a):
    filas = []
    for k in todos("pruebas"):
        try:
            filas.append(json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()))
        except Exception as e:
            print(f"  (ilegible {k}: {e})")
    if not filas:
        print("\n  No hay casos de prueba.\n")
        return
    filas.sort(key=lambda f: f.get("creado", ""))
    print(f"\n  {len(filas)} caso(s) de prueba:\n")
    for f in filas:
        print(f"    {f['caso_id']:<30} {f.get('partner','dlocal'):<14} "
              f"{f.get('variante','?'):<11} "
              f"{f.get('correo',''):<32} {f.get('creado','')}")
    print()


def borrar(a):
    registros = {}
    for k in todos("pruebas"):
        try:
            d = json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read())
            registros[d["caso_id"]] = (k, d)
        except Exception:
            pass
    if not registros:
        print("\n  No hay casos de prueba que borrar.\n")
        return

    objetivo = list(registros) if a.todos else [c for c in (a.caso or []) if c in registros]
    ajenos = [c for c in (a.caso or []) if c not in registros]
    if ajenos:
        # La única protección que importa: no borrar un caso real por un typo.
        print(f"\n  IGNORADOS (no están en el registro de pruebas): {', '.join(ajenos)}")
    if not objetivo:
        print("\n  Nada que borrar. Usá --todos o pasá un caso_id de la lista.\n")
        return

    for caso_id in objetivo:
        k_reg, d = registros[caso_id]
        rmt, mid = d["rmt"], d["message_id"]
        claves = [
            k_reg,
            _ruta("mensajes", clave_segura(mid)),
            _ruta("clientes", clave_segura(
                f"{d.get('llave', 'rmt')}|{d.get('ident', rmt)}")),
            _ruta("checklist", clave_segura(caso_id)),
        ]
        # Lo que se guarda con clave impredecible se busca por contenido.
        for col, campo in (("solicitudes", "caso_id"), ("respuestas", "caso_id"),
                           ("devoluciones", "caso_id"), ("refs", "caso_id")):
            for k in todos(col):
                try:
                    o = json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read())
                    if o.get(campo) == caso_id:
                        claves.append(k)
                except Exception:
                    pass
        for k in todos(f"acciones/{clave_segura(caso_id)}"):
            claves.append(k)
        for k in todos("adjuntos"):
            if clave_segura(caso_id) in k:
                claves.append(k)

        borradas = 0
        for k in dict.fromkeys(claves):
            try:
                s3.delete_object(Bucket=BUCKET, Key=k)
                borradas += 1
            except Exception as e:
                print(f"    no pude borrar {k}: {e}")
        print(f"  {caso_id}: {borradas} objeto(s) borrados")
    print("\n  Corré el snapshot para que desaparezcan de la pantalla.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crear", help="fabrica un caso apuntando a tu correo")
    c.add_argument("--correo", required=True, help="tu casilla, hace de cliente")
    c.add_argument("--partner", default="currencycloud", choices=sorted(PARTNERS),
                   help="con cuál partner fabricar el caso")
    c.add_argument("--variante", default="completo", choices=sorted(VARIANTES),
                   help="; ".join(f"{k}: {v['que']}" for k, v in VARIANTES.items()))
    c.add_argument("--nombre", default="", help="nombre del cliente (según la variante)")
    c.set_defaults(f=crear)

    l = sub.add_parser("listar", help="los casos de prueba vivos")
    l.set_defaults(f=listar)

    b = sub.add_parser("borrar", help="limpia casos de prueba y todo su rastro")
    b.add_argument("caso", nargs="*", help="ids a borrar")
    b.add_argument("--todos", action="store_true")
    b.set_defaults(f=borrar)

    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
