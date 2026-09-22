/* ============================================================================
   La grilla de campos de un diccionario del backend
   ----------------------------------------------------------------------------
   La usan el detalle del caso (la ficha KYC y la fila que originó la alerta) y
   la ficha del cliente (el perfil KYC). Las claves NO se conocen de antemano:
   cada reporte trae las suyas y el perfil cambia entre persona y empresa. Por
   eso es una grilla que se acomoda sola y no una tabla de columnas fijas.

   Qué campo se muestra y cómo se formatea vive en `expediente.js`, que se
   puede probar sin React.
   ========================================================================= */

import { campos } from './expediente.js';

export function Campos({ datos, vacio = null }) {
  const filas = campos(datos);
  if (filas.length === 0) return vacio;
  return (
    <div className="wt-campos">
      {filas.map((f) => (
        <div key={f.clave} className="wt-campo">
          <div className="wt-campo-etiqueta" title={f.etiqueta}>{f.etiqueta}</div>
          <div className="wt-campo-valor">{f.valor}</div>
        </div>
      ))}
    </div>
  );
}
