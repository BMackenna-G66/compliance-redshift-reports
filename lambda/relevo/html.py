"""HTML de correo a texto, preservando la estructura.

Aplastar el HTML con un `re.sub('<[^>]+>', ' ')` convierte una tabla en un
renglón corrido: «Country PA Beneficiary Last Name Castiblanco Amount USD 7572».
Las etiquetas y los valores quedan pegados y no hay forma confiable de separar
dónde termina una y empieza el otro.

Los correos de los corresponsales son casi todos tablas y listas, así que la
estructura ES el dato. Acá:

  · `</td>` y `</th>` se vuelven un separador de campo;
  · `</tr>`, `</p>`, `</div>`, `</li>`, `<br>` cortan renglón;
  · se quitan `<style>` y `<script>` enteros, con su contenido — si no, el CSS
    del correo entra como texto (aparecían líneas «table td {» en los pedidos).
"""
import html as _html
import re

_BLOQUE = re.compile(r"</\s*(?:tr|p|div|li|ul|ol|h[1-6]|table|blockquote)\s*>|<\s*br\s*/?\s*>", re.I)
_CELDA = re.compile(r"</\s*(?:td|th)\s*>", re.I)
_FUERA = re.compile(r"<\s*(script|style|head)\b.*?</\s*\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def a_texto(h):
    if not h:
        return ""
    t = _FUERA.sub(" ", h)
    t = _BLOQUE.sub("\n", t)
    t = _CELDA.sub("\t", t)
    t = _TAG.sub(" ", t)
    t = _html.unescape(t)
    t = t.replace(" ", " ").replace("‌", "")
    lineas = []
    for l in t.split("\n"):
        l = re.sub(r"[ \t]*\t[ \t]*", "\t", l)      # celdas: un solo tab
        l = re.sub(r"[^\S\t]+", " ", l).strip()
        if l:
            lineas.append(l)
    return "\n".join(lineas)
