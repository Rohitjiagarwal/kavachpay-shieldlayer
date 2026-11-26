import type { Config } from "tailwindcss";
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--bg-rgb) / <alpha-value>)",
        panel: "rgb(var(--panel-rgb) / <alpha-value>)",
        panel2: "rgb(var(--panel2-rgb) / <alpha-value>)",
        ink: "rgb(var(--ink-rgb) / <alpha-value>)",
        muted: "rgb(var(--muted-rgb) / <alpha-value>)",
        line: "rgb(var(--line-rgb) / <alpha-value>)",
        brand: "rgb(var(--brand-rgb) / <alpha-value>)",
        ok: "rgb(var(--ok-rgb) / <alpha-value>)",
        block: "rgb(var(--block-rgb) / <alpha-value>)",
        warn: "rgb(var(--warn-rgb) / <alpha-value>)",
        agent: "rgb(var(--agent-rgb) / <alpha-value>)",
        judge: "rgb(var(--judge-rgb) / <alpha-value>)",
      },
    },
  },
  plugins: [],
} satisfies Config;
