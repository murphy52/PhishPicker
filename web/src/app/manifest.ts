import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Phishpicker",
    short_name: "Phishpicker",
    description: "Real-time Phish setlist prediction",
    start_url: "/",
    display: "standalone",
    // Lock the installed PWA to portrait (honored on Android; iOS ignores it,
    // so RotateGuard provides the cross-platform landscape block).
    orientation: "portrait",
    background_color: "#0a0a0a",
    theme_color: "#0a0a0a",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  };
}
