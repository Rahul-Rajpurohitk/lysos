/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Lysos palette: dark biomedical
        ink: {
          950: "#05060a",
          900: "#0a0c14",
          800: "#11141d",
          700: "#1a1e2a",
          600: "#262b3a",
          500: "#3a4154",
        },
        accent: {
          // Teal/cyan medical
          50: "#e6fffb",
          100: "#b3fff1",
          200: "#80ffe7",
          300: "#4dffdd",
          400: "#1affd3",
          500: "#00e6b9",
          600: "#00b390",
          700: "#008066",
          800: "#004d3d",
        },
        warn: {
          400: "#ff9450",
          500: "#ff7a1a",
        },
        bad: {
          400: "#ff5a7e",
          500: "#ff2e57",
        },
        good: {
          400: "#5be584",
          500: "#22c55e",
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "ui-monospace",
          "monospace",
        ],
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: 0, transform: "translateY(4px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
