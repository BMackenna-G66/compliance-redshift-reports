"""Pipeline de extraccion y respuesta a oficios de embargo (Global66 Colombia)."""
from .extract import extraer, consolidar_por_persona          # noqa: F401
from .pipeline import procesar, MODO_PERSONA, MODO_PROCESO    # noqa: F401
from .docgen import generar_oficios                           # noqa: F401
from .validation import ValidadorCSV, ValidadorRedshift, marcar_clientes  # noqa: F401

__version__ = "0.1.0"
