import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // El repositorio tiene un package-lock.json en la raiz (solo para la CLI de
  // Supabase) ademas del de frontend/. Sin esto, Next.js infiere la raiz del
  // workspace como la del repositorio y emite un aviso.
  // Fijamos explicitamente la raiz en frontend/.
  turbopack: {
    root: path.resolve(import.meta.dirname),
  },

  experimental: {
    serverActions: {
      // SOBRE DE TRANSPORTE de Next para los Server Actions. NO es el tamano
      // maximo de un documento fiscal.
      //
      //   8 MiB  bytes maximos del artefacto fiscal  (MAX_SOURCE_XML_BYTES,
      //          en backend/app/fiscal/ingestion.py -- unica autoridad)
      //   + marco multipart: fronteras y cabeceras Content-Disposition
      //   = 9 MiB de sobre, con 1 MiB de holgura
      //
      // Se fija como numero y no como '9mb' a proposito: Next lo interpreta
      // con `bytes.parse`, que usa unidades BINARIAS -- '9mb' son 9 * 1024 *
      // 1024 --, y escribirlo asi elimina toda duda sobre si el sufijo
      // significa 10^6 o 2^20.
      bodySizeLimit: 9 * 1024 * 1024,
    },
  },
};

export default nextConfig;
