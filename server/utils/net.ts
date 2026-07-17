// THIN ADAPTER de red del sistema (node:os confinado aqui).
// URLs por las que la app es alcanzable desde otros dispositivos.
import { networkInterfaces } from 'node:os'

export function lanUrls(port: number): string[] {
  const urls: string[] = []
  for (const nics of Object.values(networkInterfaces())) {
    for (const nic of nics || []) {
      // Solo IPv4 de verdad: ni loopback ni link-local (169.254 = sin DHCP)
      if (nic.family !== 'IPv4' || nic.internal) continue
      if (nic.address.startsWith('169.254.')) continue
      urls.push(`http://${nic.address}:${port}`)
    }
  }
  return urls
}
