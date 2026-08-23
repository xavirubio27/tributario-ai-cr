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
};

export default nextConfig;
