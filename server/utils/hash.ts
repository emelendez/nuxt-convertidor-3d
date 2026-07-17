// Hashing con Web Crypto (crypto.subtle es global en Node/Bun/Deno/workers).
// SHA-1 se usa como huella de cache/reanudacion, no con fines criptograficos.

export async function sha1Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('')
}

// SHA-256 para la cookie de autenticacion por PIN (se guarda el hash, nunca
// el PIN). Comparar digests hace inocuo un compare no constante: el timing
// solo revela prefijos de un hash, no informacion del PIN.
export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('')
}
