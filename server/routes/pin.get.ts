// Formulario de PIN para clientes remotos. Handler propio (no middleware) y
// HTML autocontenido sin assets: todo lo demas esta detras del PIN.
export default defineEventHandler((event) => {
  setHeader(event, 'Content-Type', 'text/html; charset=utf-8')
  return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Convertidor 3D — Acceso</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; display: grid; place-items: center;
         min-height: 100dvh; margin: 0; background: #f4f4f5; color: #18181b; }
  @media (prefers-color-scheme: dark) { body { background: #18181b; color: #f4f4f5; } }
  form { display: flex; flex-direction: column; gap: .75rem; padding: 2rem;
         border-radius: 1rem; background: rgba(128,128,128,.08);
         border: 1px solid rgba(128,128,128,.25); min-width: 260px; }
  h1 { font-size: 1.1rem; margin: 0; }
  p { font-size: .8rem; margin: 0; opacity: .7; }
  input { font-size: 1.1rem; padding: .5rem .75rem; border-radius: .5rem;
          border: 1px solid rgba(128,128,128,.4); background: transparent; color: inherit; }
  button { font-size: 1rem; padding: .5rem; border-radius: .5rem; border: 0;
           background: #16a34a; color: #fff; cursor: pointer; }
  button:hover { background: #15803d; }
</style>
</head>
<body>
<form onsubmit="location.href='/?pin='+encodeURIComponent(document.getElementById('p').value);return false">
  <h1>🎬 Convertidor 3D</h1>
  <p>Introduce el PIN de acceso (lo muestra la consola del servidor).</p>
  <input id="p" type="password" autocomplete="off" autofocus placeholder="PIN">
  <button type="submit">Entrar</button>
</form>
</body>
</html>`
})
