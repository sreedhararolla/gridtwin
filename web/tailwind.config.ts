import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ok: "#22c55e",
        bad: "#ef4444",
        price: "#38bdf8",
        target: "#a78bfa",
        delivered: "#f59e0b",
        soc: "#34d399",
        chaos: "#f472b6",
      },
    },
  },
  plugins: [],
};

export default config;
