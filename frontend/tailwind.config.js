/** @type {import('tailwindcss').Config} */
export default {
  // Driven by src/theme.ts, which decides from the clock where the user is.
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}