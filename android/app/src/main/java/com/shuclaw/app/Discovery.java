package com.shuclaw.app;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Finds PCs running server.py by broadcasting "SHUCLAW?" on every network (USB tethering and Wi-Fi). */
final class Discovery {
    private static final int PORT = 8766;   // server.py's web port + 1
    private static final String QUERY = "SHUCLAW?", REPLY = "SHUCLAW!";

    /** Returns [{name, host, usb}], USB connections first. */
    static JSONArray find(int timeoutMs) {
        List<JSONObject> found = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        List<InterfaceAddress> locals = localAddresses();
        List<InetAddress> targets = new ArrayList<>();
        try {
            targets.add(InetAddress.getByName("255.255.255.255"));
        } catch (Exception ignored) { }
        for (InterfaceAddress a : locals) if (a.getBroadcast() != null) targets.add(a.getBroadcast());

        byte[] query = QUERY.getBytes(StandardCharsets.UTF_8);
        try (DatagramSocket sock = new DatagramSocket()) {
            sock.setBroadcast(true);
            sock.setSoTimeout(200);
            long end = System.currentTimeMillis() + timeoutMs, nextSend = 0;
            while (System.currentTimeMillis() < end) {
                if (System.currentTimeMillis() >= nextSend) {   // repeat in case a packet is lost
                    for (InetAddress t : targets) {
                        try { sock.send(new DatagramPacket(query, query.length, t, PORT)); } catch (Exception ignored) { }
                    }
                    nextSend = System.currentTimeMillis() + 500;
                }
                DatagramPacket reply = new DatagramPacket(new byte[256], 256);
                try {
                    sock.receive(reply);
                } catch (SocketTimeoutException e) {
                    continue;
                }
                String msg = new String(reply.getData(), 0, reply.getLength(), StandardCharsets.UTF_8);
                if (!msg.startsWith(REPLY)) continue;
                String[] parts = msg.substring(REPLY.length()).split("\\|");
                if (parts.length < 2) continue;
                InetAddress from = reply.getAddress();
                String host = from.getHostAddress() + ":" + parts[1];
                if (!seen.add(host)) continue;
                JSONObject pc = new JSONObject();
                pc.put("name", parts[0]);
                pc.put("host", host);
                pc.put("usb", isUsb(from, locals));
                found.add(pc);
            }
        } catch (Exception ignored) { }

        found.sort((a, b) -> Boolean.compare(!a.optBoolean("usb"), !b.optBoolean("usb")));
        return new JSONArray(found);
    }

    private static List<InterfaceAddress> localAddresses() {
        List<InterfaceAddress> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress a : ni.getInterfaceAddresses()) {
                    if (a.getAddress() instanceof Inet4Address) out.add(a);
                }
            }
        } catch (Exception ignored) { }
        return out;
    }

    /** True when the PC answered through the USB-tethering network interface. */
    private static boolean isUsb(InetAddress pc, List<InterfaceAddress> locals) {
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                String name = ni.getName();
                boolean usbIface = name.startsWith("rndis") || name.startsWith("usb") || name.startsWith("ncm");
                if (!usbIface) continue;
                for (InterfaceAddress a : ni.getInterfaceAddresses()) {
                    if (locals.contains(a) && sameSubnet(pc, a)) return true;
                }
            }
        } catch (Exception ignored) { }
        return false;
    }

    private static boolean sameSubnet(InetAddress pc, InterfaceAddress local) {
        byte[] x = pc.getAddress(), y = local.getAddress().getAddress();
        if (x.length != y.length) return false;
        int bits = local.getNetworkPrefixLength();
        for (int i = 0; i < x.length && bits > 0; i++, bits -= 8) {
            int mask = bits >= 8 ? 0xFF : (0xFF << (8 - bits)) & 0xFF;
            if ((x[i] & mask) != (y[i] & mask)) return false;
        }
        return true;
    }
}
