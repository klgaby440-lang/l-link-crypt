module.exports = {
  content: ["./app/**/*.{html,js}", "./scripts/**/*.{js,mjs}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        campagne: { light: "#FDFBF7", dark: "#131314" },
        surface: { light: "#EFECE6", dark: "#1E1F20" },
        userBg: { light: "#E3DFD5", dark: "#2B2C2F" }
      },
      animation: {
        "pulse-fast": "pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite"
      }
    }
  },
  plugins: []
};
