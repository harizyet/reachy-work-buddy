package app.reachy.companion

import app.reachy.companion.data.isTailscaleAddress
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

class TailscaleTest {
    private fun ip(s: String) = InetAddress.getByName(s).address

    @Test fun `recognises the Tailscale CGNAT range 100_64_0_0 slash 10`() {
        assertTrue(isTailscaleAddress(ip("100.64.0.1")))
        assertTrue(isTailscaleAddress(ip("100.101.102.103")))
        assertTrue(isTailscaleAddress(ip("100.127.255.254")))
    }

    @Test fun `ordinary addresses are not Tailscale`() {
        assertFalse(isTailscaleAddress(ip("100.63.255.255")))
        assertFalse(isTailscaleAddress(ip("100.128.0.1")))
        assertFalse(isTailscaleAddress(ip("192.168.1.20")))
        assertFalse(isTailscaleAddress(ip("10.0.2.15")))
        assertFalse(isTailscaleAddress(ip("::1")))
    }
}
