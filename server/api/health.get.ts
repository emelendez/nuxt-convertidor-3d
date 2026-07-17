import { getHealth } from '../utils/capabilities'
import { listenPort, loadSettings, remotePin } from '../utils/config'
import { lanUrls } from '../utils/net'
import { isLocal } from '../utils/security'

export default defineEventHandler(async (event) => {
  const local = isLocal(event)
  return {
    ...(await getHealth(await loadSettings())),
    // La UI se adapta al origen: un cliente remoto no ve acciones que solo
    // tienen sentido en la maquina servidora (dialogo nativo, Explorer).
    client_is_local: local,
    lan_urls: lanUrls(listenPort()),
    // El PIN solo se revela al operador local (para compartir URL+PIN);
    // null = acceso remoto deshabilitado.
    remote_pin: local ? (remotePin() || null) : undefined,
  }
})
