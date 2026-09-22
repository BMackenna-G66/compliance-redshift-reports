/* ============================================================================
   Los parámetros de las llamadas a la IA
   ----------------------------------------------------------------------------
   En un solo lugar porque hay tres pantallas que le piden un análisis
   —el caso, el resultado de una corrida y el historial— y lo que rompe cuando
   se separan no da error: una de ellas se queda con el tope viejo y devuelve
   análisis cortados a la mitad sin decir por qué.

   8192 y no 2048: un análisis de cuatro secciones sobre una ficha completa da
   unos 8.000 caracteres y chocaba con MAX_TOKENS. El backend ahora avisa
   cuando pasa, pero mejor que no pase.

   0.3 de temperatura: esto se lee dentro de un expediente de compliance.
   Cuanto menos invente, mejor.
   ========================================================================= */

export const MAX_TOKENS_IA = 8192;
export const TEMPERATURA_IA = 0.3;
