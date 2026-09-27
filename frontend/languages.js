// Nombre legible de un código de idioma ("es" -> "Español"), con el
// Intl del navegador y el código tal cual como respaldo.
function languageLabel(code) {
  try {
    const name = new Intl.DisplayNames(["es"], { type: "language" }).of(code);
    return name.charAt(0).toUpperCase() + name.slice(1);
  } catch {
    return code;
  }
}
