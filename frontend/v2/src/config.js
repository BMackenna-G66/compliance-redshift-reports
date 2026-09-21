/* ============================================================================
   Configuración
   ----------------------------------------------------------------------------
   Se lee de `config.json`, que el workflow de despliegue escribe con los
   secrets del repositorio. NO se compila dentro del bundle: así el mismo
   build sirve para cualquier entorno y no hay que rehacerlo para cambiar una
   URL.

   Se pide con ruta relativa porque la app vive en una subcarpeta
   (`/compliance-redshift-reports/v2/`) y una ruta absoluta la buscaría en la
   raíz del dominio.
   ========================================================================= */

let cache = null;

export async function cargarConfig() {
  if (cache) return cache;
  const r = await fetch('./config.json', { cache: 'no-store' });
  if (!r.ok) throw new Error(`config.json respondió ${r.status}`);
  const cfg = await r.json();
  if (!cfg.apiUrl) throw new Error('config.json no trae apiUrl');
  cache = { apiUrl: String(cfg.apiUrl).replace(/\/$/, '') };
  return cache;
}
