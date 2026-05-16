import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#0f3d2f",
          dark: "#082a21",
          light: "#1a5240",
        },
        forest: {
          DEFAULT: "#0f3d2f",
          deep: "#082a21",
          muted: "#1a5240",
        },
        mist: {
          DEFAULT: "#f4f6f3",
          line: "#dce0db",
          paper: "#fafbf9",
        },
        ink: {
          DEFAULT: "#0c1412",
          muted: "#4a5752",
        },
        surface: {
          DEFAULT: "#f4f6f3",
          muted: "#e8ebe6",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
      },
      fontSize: {
        "display-sm": ["2rem", { lineHeight: "1.15", letterSpacing: "-0.02em" }],
        display: ["2.5rem", { lineHeight: "1.1", letterSpacing: "-0.025em" }],
      },
      boxShadow: {
        soft: "0 12px 40px -16px rgba(12, 20, 18, 0.12)",
        card: "0 1px 0 rgba(12, 20, 18, 0.04), 0 8px 24px -12px rgba(12, 20, 18, 0.08)",
        "elev-1": "0 1px 2px rgba(12, 20, 18, 0.06), 0 4px 12px -4px rgba(12, 20, 18, 0.08)",
        "elev-2": "0 8px 32px -12px rgba(12, 20, 18, 0.14)",
      },
      keyframes: {
        shimmer: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.35s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
