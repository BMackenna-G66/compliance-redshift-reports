"""Motor de extraccion de identificadores de transaccion desde correos de corresponsales.

Cinco pasos, en este orden (Metodo de extraccion §1):
  1. identificar el partner   -> partner.py    (X-Original-Sender, no From)
  2. clasificar el tipo       -> clasificar.py (accionable vs informativo)
  3. extraer el identificador -> extraer.py    (regex declarativa por partner)
  4. validar                  -> validar.py    (rango, formato, normalizacion)
  5. consultar Redshift       -> redshift.py + cliente.py (el unico paso con red)

Los pasos 1 a 4 no tienen dependencias externas ni tocan la red: solo stdlib.
El paso 5 necesita un driver (redshift_connector o psycopg2) y esta aislado
a proposito, para que todo lo de arriba se pueda correr y medir sin nada.
"""
from .reglas import cargar_reglas          # noqa: F401
from .pipeline import procesar, procesar_lote  # noqa: F401

__version__ = "0.1.0"
