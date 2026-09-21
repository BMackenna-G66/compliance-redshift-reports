/* ============================================================================
   Sesión
   ----------------------------------------------------------------------------
   Firebase Auth con Google restringido a @global66.com, y el perfil (rol +
   módulos) desde la colección `wt_roles` de Firestore. Es el mismo backend de
   identidad que v1: los dos fronts van a convivir y tienen que leer al mismo
   usuario del mismo lugar.

   Sobre la configuración de Firebase que está acá abajo en claro: la `apiKey`
   de un proyecto web de Firebase es un identificador público, no un secreto —
   viaja en cada request desde el navegador y así está también en v1. Lo que
   protege los datos son las reglas de Firestore, no esconder esto.
   ========================================================================= */

import { useEffect, useMemo, useRef, useState } from 'react';
import { initializeApp } from 'firebase/app';
import {
  GoogleAuthProvider, getAuth, onAuthStateChanged, signInWithPopup, signOut,
} from 'firebase/auth';
import {
  collection, deleteDoc, doc, getDoc, getDocs, getFirestore, setDoc,
} from 'firebase/firestore';

import {
  PERFIL_MINIMO, PERFIL_NUEVO, SUPER_ADMIN, esAdmin, perfilRecordado,
  recordarPerfil,
} from './permisos.js';

const app = initializeApp({
  apiKey: 'AIzaSyCKduUg-DLxeOEx7ZDTbS8TpxRdTVyFMjI',
  authDomain: 'global66-compliance.firebaseapp.com',
  projectId: 'global66-compliance',
  storageBucket: 'global66-compliance.firebasestorage.app',
  messagingSenderId: '925688930751',
  appId: '1:925688930751:web:5c58f2f0ad3e73c102810a',
});

const auth = getAuth(app);
const db = getFirestore(app);

const proveedor = new GoogleAuthProvider();
proveedor.setCustomParameters({ hd: 'global66.com' });

export function entrar() {
  return signInWithPopup(auth, proveedor);
}

export function salir() {
  return signOut(auth);
}

/** Lee el perfil de Firestore, con las mismas reglas que v1. */
async function leerPerfil(email) {
  if (email === SUPER_ADMIN) return { rol: 'superadmin', modulos: ['all'] };

  try {
    const ref = doc(db, 'wt_roles', email);
    const snap = await getDoc(ref);

    if (snap.exists()) {
      const d = snap.data();
      return { rol: d.role || 'analyst', modulos: d.modules || ['dashboard', 'alertas'] };
    }

    // Usuario nuevo: se le crea la entrada por defecto. Si la escritura falla
    // no importa —se reintenta la próxima vez que entre— pero el perfil que
    // devolvemos es el mismo igual, para que pueda trabajar hoy.
    setDoc(ref, {
      role: PERFIL_NUEVO.rol,
      modules: PERFIL_NUEVO.modulos,
      grantedBy: 'auto',
      grantedAt: new Date().toISOString(),
    }).catch(() => {});
    return PERFIL_NUEVO;
  } catch {
    // Firestore no contesta. Se usa lo último que se supo de este usuario; si
    // nunca se supo nada, el perfil mínimo. Nunca acceso total: ver permisos.js.
    return perfilRecordado();
  }
}

/**
 * El estado de la sesión.
 *
 * Devuelve también `perfilRef`, que es el perfil dentro de una caja mutable.
 * Suena raro y tiene un motivo concreto: el cliente de API se arma una sola
 * vez, y si le pasáramos el perfil como valor se quedaría con el que había en
 * ese momento —el mínimo, porque Firestore todavía no contestó— y bloquearía
 * como "sólo lectura" todo lo que el usuario escriba después.
 */
export function useSesion() {
  const [cargando, setCargando] = useState(true);
  const [email, setEmail] = useState('');
  const [perfil, setPerfil] = useState(PERFIL_MINIMO);
  const [error, setError] = useState('');

  const perfilRef = useRef(PERFIL_MINIMO);
  const emailRef = useRef('');
  perfilRef.current = perfil;
  emailRef.current = email;

  useEffect(() => {
    return onAuthStateChanged(auth, async (usuario) => {
      if (!usuario) {
        setEmail('');
        setPerfil(PERFIL_MINIMO);
        setCargando(false);
        return;
      }
      const correo = usuario.email || '';
      setEmail(correo);
      try {
        const p = await leerPerfil(correo);
        setPerfil(p);
        recordarPerfil(p);
      } catch (e) {
        setError(String(e?.message || e));
        setPerfil(perfilRecordado());
      } finally {
        setCargando(false);
      }
    });
  }, []);

  return useMemo(
    () => ({
      cargando,
      email,
      perfil,
      error,
      autenticado: Boolean(email),
      leerPerfilActual: () => perfilRef.current,
      leerEmailActual: () => emailRef.current,
    }),
    [cargando, email, perfil, error],
  );
}

/* ── Los perfiles, para la pantalla de administración ───────────────────────
   Viven en Firestore y NO en la API: es el mismo lugar que lee v1, y tiene
   que serlo — los dos fronts van a convivir y un permiso quitado en uno
   tiene que valer en el otro.

   Estas tres funciones son las únicas que escriben permisos. La capa de API
   no las ve, así que su corte de sólo lectura no las cubre: cada una revisa
   el perfil de quien llama.

   ESA REVISIÓN ES CORTESÍA, NO SEGURIDAD. Corre en el navegador y cualquiera
   con las herramientas de desarrollo la saltea. Lo que de verdad protege
   `wt_roles` son las reglas de Firestore, del lado del servidor. Acá está
   para que la pantalla no ofrezca algo que va a fallar, y para que un
   descuido de programación no escriba permisos desde un perfil que no debe. */

const COLECCION = 'wt_roles';

/* Documentos de la colección que NO son personas. v1 guarda acá la lista de
   destinatarios de notificaciones, aprovechando que la colección ya está
   permitida. Si se mostraran como usuarios, aparecería un «usuario» llamado
   `__notif__` que nadie sabe qué es — y borrarlo rompería las notificaciones. */
const NO_SON_PERSONAS = (id) => id.startsWith('__') && id.endsWith('__');

export async function listarPerfiles() {
  const snap = await getDocs(collection(db, COLECCION));
  const salida = [];
  snap.forEach((d) => {
    if (NO_SON_PERSONAS(d.id)) return;
    const v = d.data() || {};
    salida.push({ email: d.id, role: v.role || '', modules: v.modules || [],
                  grantedBy: v.grantedBy || '', grantedAt: v.grantedAt || '' });
  });
  return salida;
}

export async function guardarPerfil(perfilDeQuienGuarda, correo, datos) {
  if (!esAdmin(perfilDeQuienGuarda)) {
    throw new Error('Sólo un administrador puede cambiar permisos.');
  }
  const id = String(correo || '').trim().toLowerCase();
  if (!id) throw new Error('Falta el correo.');
  await setDoc(doc(db, COLECCION, id), {
    role: datos.role,
    modules: datos.modules,
    grantedBy: datos.grantedBy || '',
    grantedAt: new Date().toISOString(),
  });
}

export async function borrarPerfil(perfilDeQuienGuarda, correo) {
  if (!esAdmin(perfilDeQuienGuarda)) {
    throw new Error('Sólo un administrador puede quitar permisos.');
  }
  const id = String(correo || '').trim().toLowerCase();
  if (NO_SON_PERSONAS(id)) throw new Error('Ese documento no es un usuario.');
  await deleteDoc(doc(db, COLECCION, id));
}
