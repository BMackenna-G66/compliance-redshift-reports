/* ============================================================================
   Catálogo de reportes
   ----------------------------------------------------------------------------
   La primera pantalla real de v2, y está acá por una razón concreta: es el
   criterio de salida de la Fase 1. Ejercita la cadena completa —config →
   sesión → permisos → API → tabla— contra datos de producción de verdad, y
   es de sólo lectura, así que no puede romper nada mientras se prueba.

   Ejecutar un reporte es de la Fase 4. Acá sólo se lista el catálogo.
   ========================================================================= */

import { useCallback, useEffect, useState } from 'react';
import { Tabla } from '../comun/Tabla.jsx';
import { COLOR_CATEGORIA, COLOR_CATEGORIA_POR_DEFECTO } from '../dominio.js';

function Categoria({ reporte }) {
  const color = COLOR_CATEGORIA[reporte.category] || COLOR_CATEGORIA_POR_DEFECTO;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span
        aria-hidden="true"
        style={{
          width: 8, height: 8, borderRadius: '50%',
          background: color, flex: 'none',
        }}
      />
      {/* La etiqueta legible la manda el backend; si faltara, mejor la clave
          cruda que una celda vacía que parece un bug. */}
      {reporte.category_label || reporte.category || '—'}
    </span>
  );
}

const COLUMNAS = [
  {
    clave: 'display_name',
    titulo: 'Reporte',
    ancho: '26%',
    render: (r) => r.display_name || r.report_name,
  },
  {
    clave: 'category_label',
    titulo: 'Categoría',
    ancho: '16%',
    render: (r) => <Categoria reporte={r} />,
  },
  {
    clave: 'description',
    titulo: 'Qué hace',
    // Lo único que se deja romper en varias líneas: es prosa, y truncarla
    // dejaría la columna inútil.
    render: (r) => (
      <span style={{ whiteSpace: 'normal', display: 'block', maxWidth: 560 }}>
        {r.description || '—'}
      </span>
    ),
  },
  {
    clave: 'n_params',
    titulo: 'Parámetros',
    tipo: 'numero',
    ancho: '9%',
    buscable: false,
    render: (r) => (r.params?.length ?? 0),
  },
  {
    clave: 'origen',
    titulo: 'Origen',
    ancho: '9%',
    render: (r) => (r.is_custom ? 'A medida' : 'Del sistema'),
    exportar: (r) => (r.is_custom ? 'A medida' : 'Del sistema'),
  },
  { clave: 'report_name', titulo: 'Clave', tipo: 'mono', ancho: '18%' },
];

export function Reportes({ api }) {
  const [reportes, setReportes] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  const cargar = useCallback(async () => {
    setCargando(true);
    setError('');
    try {
      const d = await api.get('/reports');
      // `n_params` se precalcula porque la tabla ordena por el valor de la
      // clave, y no puede ordenar por algo que sólo existe en el `render`.
      setReportes((d?.reports || []).map((r) => ({ ...r, n_params: r.params?.length ?? 0 })));
    } catch (e) {
      setError(e?.message || 'No se pudo cargar el catálogo.');
    } finally {
      setCargando(false);
    }
  }, [api]);

  useEffect(() => { cargar(); }, [cargar]);

  return (
    <Tabla
      titulo={`Reportes AML${reportes.length ? ` · ${reportes.length}` : ''}`}
      columnas={COLUMNAS}
      filas={reportes}
      cargando={cargando}
      error={error}
      alReintentar={cargar}
      nombreExport="reportes-watchtower"
      claveFila={(r) => r.report_name}
      porPagina={40}
      herramientas={
        <button className="wt-btn" onClick={cargar} disabled={cargando}>
          Refrescar
        </button>
      }
    />
  );
}
