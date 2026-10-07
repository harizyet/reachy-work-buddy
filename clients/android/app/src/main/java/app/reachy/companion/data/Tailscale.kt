package app.reachy.companion.data

import java.net.Inet4Address
import java.net.NetworkInterface

/** Tailscale hands every device an address in the CGNAT range 100.64.0.0/10. */
fun isTailscaleAddress(address: ByteArray): Boolean =
    address.size == 4 && (address[0].toInt() and 0xFF) == 100 && (address[1].toInt() and 0xC0) == 0x40

/** True when this phone has a Tailscale address on an interface that is up (i.e. the Tailscale VPN is connected). */
fun tailscaleActive(interfaces: () -> List<NetworkInterface>? = { NetworkInterface.getNetworkInterfaces()?.toList() }): Boolean =
    runCatching {
        interfaces().orEmpty().any { nic ->
            nic.isUp && nic.inetAddresses.toList().any { it is Inet4Address && isTailscaleAddress(it.address) }
        }
    }.getOrDefault(false)
