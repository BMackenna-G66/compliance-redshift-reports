/* ============================================================================
   «¿Sigue montada la pantalla?»
   ----------------------------------------------------------------------------
   Varias pantallas sondean: ejecutar un reporte, cosechar un analítico, correr
   el chequeo institucional. Todas necesitan lo mismo —dejar de pedir cuando
   quien miraba se fue— y todas lo resolvían con una bandera propia.

   ESTÁ ACÁ PORQUE ESCRIBIRLA A MANO SALE MAL DE DOS FORMAS, Y LAS DOS PASARON:

   · Apagarla en el desmontaje y no volver a encenderla al montar. React monta,
     desmonta y vuelve a montar cada componente en desarrollo, así que la
     bandera quedaba apagada para siempre y el sondeo se cancelaba antes de la
     primera vuelta. La pantalla se quedaba en «Consultando…» sin pedir nada.
     Se descubrió mirando la red: el disparo salía y la cosecha no.

   · Declararla y no apagarla nunca, que es no tener nada: el sondeo sigue
     pegándole a la API contra un componente que ya no existe, y cada
     navegación deja uno más corriendo.

   El orden importa: se enciende al montar, se apaga al desmontar.
   ========================================================================= */

import { useEffect, useRef } from 'react';

/**
 * Un `ref` que vale `true` mientras la pantalla está montada.
 *
 * Se lee `vivo.current` —no se desestructura— porque el valor tiene que
 * consultarse en el momento, no capturarse cuando arrancó el sondeo.
 */
export function useVivo() {
  const vivo = useRef(true);
  useEffect(() => {
    vivo.current = true;
    return () => { vivo.current = false; };
  }, []);
  return vivo;
}
