import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],

  // La app se publica en GitHub Pages bajo /compliance-redshift-reports/v2/.
  // Con base absoluta ('/') los assets se pedirían a la raíz del dominio y
  // darían 404. Relativa funciona en Pages y también abriendo el dist a mano.
  base: './',

  build: {
    outDir: 'dist',

    // Dos entradas: la app y el banco de pruebas. El banco NO llega al sitio
    // publicado —el workflow lo borra— pero se construye acá para que se
    // rompa el build si un componente deja de compilar, y no en silencio.
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.html'),
        banco: resolve(__dirname, 'banco.html'),
      },
    },

    // El prototipo tiene 20 pantallas; sin esto Vite avisa por el tamaño del
    // bundle en cada build y el aviso deja de leerse.
    chunkSizeWarningLimit: 900,
  },
});
