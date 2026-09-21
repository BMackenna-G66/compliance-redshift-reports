/* ============================================================================
   Ruteo
   ----------------------------------------------------------------------------
   Por hash (`#/casos`), no por ruta (`/v2/casos`).

   No es nostalgia: GitHub Pages sirve archivos estáticos y no sabe devolver
   `index.html` para una ruta que no existe como archivo. Con rutas de verdad,
   entrar directo a `/v2/casos` o recargar la página daría un 404 de GitHub —
   y recargar estando en una pantalla es lo más normal del mundo. El hash
   nunca llega al servidor, así que funciona sin configurar nada.

   Si algún día v2 se sirve desde un dominio propio con fallback a index.html,
   esto se cambia acá y en ningún otro lado.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';

export function rutaActual(hash = globalThis.location?.hash || '') {
  const limpio = String(hash).replace(/^#\/?/, '').trim();
  if (!limpio) return { id: '', params: {} };
  const [camino, consulta = ''] = limpio.split('?');
  const partes = camino.split('/').filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(consulta));
  // `#/caso/abc123` → id 'caso', resto ['abc123']
  return { id: partes[0] || '', resto: partes.slice(1), params };
}

export function irA(id, resto = []) {
  const camino = [id, ...resto].filter(Boolean).join('/');
  globalThis.location.hash = '#/' + camino;
}

export function useRuta(porDefecto = 'dashboard') {
  const [ruta, setRuta] = useState(() => rutaActual());

  useEffect(() => {
    const alCambiar = () => setRuta(rutaActual());
    globalThis.addEventListener('hashchange', alCambiar);
    return () => globalThis.removeEventListener('hashchange', alCambiar);
  }, []);

  // Entrar sin hash tiene que llevar a algún lado.
  useEffect(() => {
    if (!ruta.id) irA(porDefecto);
  }, [ruta.id, porDefecto]);

  const navegar = useCallback((id, resto) => irA(id, resto), []);

  return { ruta: ruta.id || porDefecto, resto: ruta.resto || [], params: ruta.params, navegar };
}
