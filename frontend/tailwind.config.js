/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          500: '#0071E3',
          600: '#0066CC',
          700: '#0052A3'
        }
      },
      boxShadow: {
        soft: '0 8px 32px rgba(15, 23, 42, 0.08)'
      }
    }
  },
  plugins: []
}
