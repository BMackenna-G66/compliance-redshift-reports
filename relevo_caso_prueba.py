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
        "pedidos": ["✔ Front of the document", "✔ Back of the document",
                    "✔ Statement of source of funds", "✔ Purpose of payment"],
    },
    "empresa": {
        "que": "razón social — verifica el trato de usted y plural",
        "nombre": "MACKENNA SOLUCIONES SPA",
        "pedidos": ["✔ Statement of source of funds", "✔ Nature of business",
                    "✔ Website"],
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
        "pedidos": ["✔ Statement of source of funds"],
    },
}


def _cuerpo(rmt, nombre, pedidos):
    lineas = [
        "d•local", "Dear Global 66 - XB,",
        "We would like to advise that we have received a payout request for the "
        "transaction below:",
        "Country\tCL",
        f"Beneficiary Last Name\t{nombre.split()[-1]}\tAmount\tUSD 1234",
        f"Beneficiary Name\t{nombre.split()[0]}\tPayout ID\t9{rmt}",
        f"External ID\tRMT0{rmt}",
    ]
    if pedidos:
        lineas.append("According to our Payments Policy and International Compliance "
                      "Standards, there are certain circumstances where we require "
                      "additional information.")
        lineas.append("Supporting documentation required to continue processing payouts:")
        lineas += pedidos
    # La marca de "esto es una prueba" NO va en el cuerpo: cae dentro de la
    # ventana que el motor barre después de un arranque y termina extraída
    # como si fuera un requerimiento del partner. Verificado. Va en un header.
    lineas.append("Sent by dLocal , payment service provider for Global 66 - XB.")
    return "\n".join(lineas)


def crear(a):
    v = VARIANTES[a.variante]
    rmt = str(BASE_RMT + int(time.time()) % 9999)
    caso_id = f"dlocal:rmt:{rmt}"
    mid = f"PRUEBA-{rmt}"
    nombre = a.nombre or v["nombre"]

    poner("mensajes", clave_segura(mid), {
        "id": mid, "thread_id": mid,
        "asunto": f"New RFI is requested - RMT0{rmt}",
        "cuerpo": _cuerpo(rmt, nombre, v["pedidos"]),
        "headers": {
            "From": "\"'d·Local' via Compliance\" <compliance@global66.com>",
            "To": "compliance@global66.com",
            "X-Original-Sender": "no_reply@dlocal.com",
            "Reply-To": "\"d·Local\" <no_reply@dlocal.com>",
            "Subject": f"New RFI is requested - RMT0{rmt}",
            "Date": time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime()),
            "Message-ID": f"<{mid}@prueba.local>",
            "List-ID": "<compliance.global66.com>",
            "X-Relevo-Prueba": "relevo_caso_prueba.py",
        },
        "texto_adjuntos": [], "esperado": None,
        "fecha": str(int(time.time() * 1000)), "_prueba": True,
    })

    poner("clientes", clave_segura(f"rmt|{rmt}"), {
        "llave": "rmt", "valor": rmt, "estado": "encontrado",
        "motivo": "CASO DE PRUEBA — resolución inyectada, no salió de Redshift",
        "cliente": {
            "cliente_id": 999000000 + int(rmt) % 1000,
            "cliente_nombre": nombre, "cliente_correo": a.correo,
            "cliente_pais": "Chile",
            "tx_monto": "1234.00", "tx_moneda": "USD",
            "tx_fecha": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "tx_estado": "PRUEBA",
            "tx_beneficiario": nombre, "tx_remitente": nombre,
            "extra": {"ref_nuestra": f"RMT0{rmt}", "_prueba": True},
        },
        "verificacion": {}, "filas": 1, "ms": 0,
        "cuando": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "_prueba": True,
    })

    poner("pruebas", clave_segura(caso_id), {
        "caso_id": caso_id, "rmt": rmt, "message_id": mid,
        "variante": a.variante, "correo": a.correo, "nombre": nombre,
        "creado": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    })

    print(f"\n  Caso creado: {caso_id}")
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
        print(f"    {f['caso_id']:<28} {f.get('variante','?'):<11} "
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
            _ruta("clientes", clave_segura(f"rmt|{rmt}")),
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
