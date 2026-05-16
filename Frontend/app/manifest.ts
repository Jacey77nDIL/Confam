import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Confam",
    short_name: "Confam",
    description:
      "Price clarity and transfer checks for Nigerian shoppers — markets, voice, and bank screenshots in one place.",
    start_url: "/chat",
    display: "standalone",
    background_color: "#f4f6f3",
    theme_color: "#0f3d2f",
    orientation: "portrait-primary",
    icons: [
      {
        src: "/icons/confam.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
    ],
  };
}
