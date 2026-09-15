"""Rehace las plantillas de correo sobre la base nueva de Global66.

Trasplanta el CUERPO de cada plantilla tal cual está —ni una palabra cambia—
y lo mete en la base nueva. Los marcadores que usa el renderizador viven
dentro del cuerpo, así que siguen funcionando sin tocar código:

    {!Account.first_name__c}   el nombre
    {{N}}                      la numeración, que se recalcula al quitar bloques
    <!--B:x--> ... <!--/B-->   los bloques removibles
    TEXTO LIBRE<br>x3          el hueco del texto libre

El cuerpo lo saca SIEMPRE de la version en HEAD, no del archivo en disco, para
que correr esto dos veces de el mismo resultado en vez de migrar lo ya migrado.
Eso significa que si se edita el TEXTO de un correo, hay que commitear ese
cambio antes de volver a correr esto, o se pisa con la version de HEAD.

Se corre desde la raiz del repo:

    python3 regenerar_plantillas.py

Cuando tocar esto: al cambiar `lambda/templates/_base_global66.html` (el
caparazon corporativo comun) o la clausula de respuesta. Las plantillas que
salen ESTAN commiteadas y son las que lee la Lambda; este script no corre en
runtime, solo las regenera.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent
R = REPO / "lambda"


def original(rel):
    """El archivo tal como esta en HEAD, para que la migracion sea repetible."""
    r = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{rel}"],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"no pude leer HEAD:{rel} — {r.stderr.strip()}")
    return r.stdout


def rellena(base, cuerpo, boton, trato="tu"):
    """Cambia los dos huecos, y solo esos dos.

    Los marcadores van entre arrobas dobles porque la version anterior usaba
    las palabras sueltas CUERPO y BOTON, que tambien aparecian en los
    comentarios de la base: el replace las tomaba a todas y el correo salia
    con el cuerpo duplicado y un comentario partido al medio.
    """
    for marca, valor in (("@@CUERPO@@", cuerpo), ("@@BOTON@@", boton),
                         ("@@CLAUSULA@@", CLAUSULA[trato])):
        if base.count(marca) != 1:
            raise SystemExit(f"{marca} aparece {base.count(marca)} veces en la base")
        base = base.replace(marca, valor)
    return base
BASE = (R / "templates" / "_base_global66.html").read_text(encoding="utf-8")
CDN = "https://di7f123v3u2y5.cloudfront.net/formularios"

# La cláusula de respuesta, en los dos tratos. La formal va donde el
# destinatario es una empresa: un correo que trata de usted en el cuerpo y de
# tú en el pie se lee como armado con partes de dos correos distintos.
CLAUSULA = {
    "tu": ("Respóndenos este correo adjuntando tus documentos a la brevedad. "
           "Conserva el asunto tal como está, así podemos vincular tu respuesta "
           "y procesar tu caso sin demoras."),
    "usted": ("Respóndannos este correo adjuntando sus documentos a la brevedad. "
              "Conserven el asunto tal como está, así podemos vincular su respuesta "
              "y procesar su caso sin demoras."),
}

BOTON = '''<table class="button_block block-4" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0"><tr><td class="pad" style="padding-top:10px;padding-bottom:30px;padding-left:10px;padding-right:10px" align="center"><a href="{url}" target="_blank" style="color:#ffffff;text-decoration:none;"><!--[if mso]>
<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{url}" style="height:45px;width:230px;v-text-anchor:middle;" arcsize="58%" fillcolor="#1f49b6">
<v:stroke dashstyle="Solid" weight="0px" color="#1f49b6"/>
<w:anchorlock/>
<v:textbox inset="0px,0px,0px,0px">
<center dir="false" style="color:#ffffff;font-family:sans-serif;font-size:16px">
<![endif]-->
<span class="button" style="background-color:#1f49b6;mso-shading:transparent;border-radius:26px;color:#ffffff;display:inline-block;font-family:Montserrat,Trebuchet MS,Lucida Grande,Lucida Sans Unicode,Lucida Sans,Tahoma,sans-serif;font-size:16px;font-weight:400;mso-border-alt:none;padding:7px 25px;text-align:center;width:auto;word-break:keep-all;letter-spacing:normal;"><span style="word-break:break-word;line-height:32px;">{texto}</span></span>
<!--[if mso]></center></v:textbox></v:roundrect><![endif]--></a></td></tr></table>'''


def cuerpo_de(html):
    """El cuerpo visible, desde el saludo hasta la firma, tal cual."""
    i = html.find("{!Account.first_name__c}")
    if i < 0:
        raise SystemExit("no encontré el marcador del nombre")
    # Hacia atrás hasta abrir el <p> del saludo.
    ini = html.rfind("<p ", 0, i)
    fin = html.find("Equipo Global66", i)
    fin = html.find("</p>", fin) + 4
    return html[ini:fin]


PLANTILLAS = {
    "email_general_b2c.html":        ("Formulario_KYC_Individual_Global.pdf", "Descargar formulario", "tu"),
    "email_argentina_b2c.html":      ("Formulario_KYC_Individual_Global.pdf", "Descargar formulario", "tu"),
    "email_b2b_generico.html":       ("Formulario_B2B.pdf", "Descargar formulario", "usted"),
    "email_general_b2c_blanco.html": ("Formulario_KYC_Individual_Global.pdf", "Descargar formulario", "tu"),
    "email_texto_libre.html":        (None, None, "tu"),
}

for nombre, (pdf, texto_boton, trato) in PLANTILLAS.items():
    ruta = R / "templates" / nombre
    viejo = original(f"lambda/templates/{nombre}")
    cuerpo = cuerpo_de(viejo)
    boton = BOTON.format(url=f"{CDN}/{pdf}", texto=texto_boton) if pdf else ""
    # Si la plantilla tiene bloques removibles, el boton viaja dentro del mismo
    # bloque que el punto "Formulario adjunto, completo y firmado": cuando el
    # analista destilda esa categoria el punto desaparece del texto, y un boton
    # azul ofreciendo un formulario que el correo ya no menciona queda huerfano.
    if boton and "<!--B:formulario-->" in viejo:
        boton = "<!--B:formulario-->" + boton + "<!--/B-->"
    nuevo = rellena(BASE, cuerpo, boton, trato)
    ruta.write_text(nuevo, encoding="utf-8")
    print(f"  {nombre:<34} cuerpo {len(cuerpo):>5} · botón {'sí' if pdf else 'no':<3} · {trato:<5} · total {len(nuevo)}")

# Relevo usa el mismo caparazón para el cliente.
base_relevo = R / "relevo" / "plantillas" / "base.html"
cuerpo = cuerpo_de(original("lambda/relevo/plantillas/base.html"))
base_relevo.write_text(rellena(BASE, cuerpo, "", "tu"), encoding="utf-8")
print(f"  relevo/base.html{'':<18} cuerpo {len(cuerpo):>5} · botón no")


# ── la del partner ───────────────────────────────────────────────────────
# Mismo caparazón corporativo, pero NO lleva la cláusula de respuesta: esa le
# habla al cliente ("adjuntá tus documentos") y del otro lado hay un analista
# de un banco corresponsal. En su lugar va el pie propio, que el compositor
# escribe en el idioma del correo.
CLAUSULA_INI = '<!-- La cláusula de respuesta.'
CLAUSULA_FIN = '<!-- pie -->'

PIE_PARTNER = '''<table class="text_block block-6" width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="mso-table-lspace:0;mso-table-rspace:0;word-break:break-word"><tr><td class="pad" style="padding:6px 25px 24px 25px"><div style="font-family:Montserrat,'Trebuchet MS','Lucida Grande','Lucida Sans Unicode','Lucida Sans',Tahoma,sans-serif;font-size:12px;line-height:1.5;color:#5d65ac;border-top:1px solid #e3e5ee;padding-top:14px"><p style="margin:0;font-size:12px">@@PIE@@</p></div></td></tr></table>

'''

partner = BASE
i, f = partner.find(CLAUSULA_INI), partner.find(CLAUSULA_FIN)
if i < 0 or f < 0 or f < i:
    raise SystemExit("no ubiqué el bloque de la cláusula en la base")
partner = partner[:i] + PIE_PARTNER + partner[f:]
# El cuerpo del partner son bloques (<p>, <ol>, <blockquote>), no un span, así
# que el contenedor fija el tamaño: los bloques no traen font-size propio.
partner = partner.replace("font-size:12px;font-family:Montserrat", "font-size:15px;font-family:Montserrat", 1)
partner = partner.replace("@@BOTON@@", "")
if "@@CLAUSULA@@" in partner:
    raise SystemExit("la cláusula del cliente no debería sobrevivir en partner.html")
for marca in ("@@CUERPO@@", "@@PIE@@"):
    if partner.count(marca) != 1:
        raise SystemExit(f"{marca} aparece {partner.count(marca)} veces en partner.html")
(R / "relevo" / "plantillas" / "partner.html").write_text(partner, encoding="utf-8")
print(f"  relevo/partner.html{'':<15} total {len(partner)}")
