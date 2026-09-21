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
import { doc, getDoc, getFirestore, setDoc } from 'firebase/firestore';

import {
  PERFIL_MINIMO, PERFIL_NUEVO, SUPER_ADMIN, perfilRecordado, recordarPerfil,
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
