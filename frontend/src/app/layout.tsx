import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Asistente Tributario IA — Costa Rica",
  description:
    "Capa de inteligencia tributaria sobre los datos fiscales reales del contribuyente.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es">
      <body className="antialiased">{children}</body>
    </html>
  );
}
