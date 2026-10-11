package expo.modules.xraycore;

import java.io.*;
import java.net.*;
import android.os.ParcelFileDescriptor;

// Runs under Android ART via app_process; no credentials or production traffic.
class GcXrayLastCore {
  public native String gcInit(String home);
  public native String gcStart(String config, int fd);
  public native void gcStop();
  public native String gcVersion();
}

public class Smoke {
  static native int openTun();
  static native boolean fdOpen(int fd);
  static native void closeFd(int fd);
  static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
  public static void main(String[] args) throws Exception {
    System.load(args[0]);
    GcXrayLastCore core = new GcXrayLastCore();
    require(core.gcInit(args[1]).isEmpty(), "init");
    System.out.println("VERSION=" + core.gcVersion());
    require(core.gcVersion().contains("26.10.10"), "upstream version");
    ParcelFileDescriptor[] pipe = ParcelFileDescriptor.createPipe();
    int before = new File("/proc/self/fd").list().length;
    for (int i = 0; i < 30; i++) {
      require(!core.gcStart("{bad json", pipe[0].getFd()).isEmpty(), "bad config accepted");
      core.gcStop();
    }
    require(new File("/proc/self/fd").list().length <= before + 2, "fd leak on failed start");
    // The wrapper borrows Java's FD: repeated failed starts/stop must not close it.
    OutputStream writer = new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1]);
    writer.write(42); writer.flush();
    InputStream reader = new ParcelFileDescriptor.AutoCloseInputStream(pipe[0]);
    require(reader.read() == 42, "Java original descriptor closed");
    reader.close(); writer.close();
    String config = "{\"log\":{\"loglevel\":\"warning\"},\"inbounds\":[{\"listen\":\"127.0.0.1\",\"port\":19483,\"protocol\":\"socks\",\"settings\":{\"auth\":\"noauth\",\"udp\":true}}],\"outbounds\":[{\"protocol\":\"freedom\"}]}";
    for (int i = 0; i < 3; i++) {
      require(core.gcStart(config, -1).isEmpty(), "start");
      require(core.gcStart(config, -1).contains("already running"), "double start");
      ServerSocket server = new ServerSocket(19484, 1, InetAddress.getByName("127.0.0.1"));
      Thread responder = new Thread(() -> {
        try (Socket accepted = server.accept()) {
          accepted.getOutputStream().write("SMOKE_OK".getBytes("UTF-8"));
        } catch (Exception e) { throw new RuntimeException(e); }
      });
      responder.start();
      try (Socket proxy = new Socket("127.0.0.1", 19483)) {
        proxy.setSoTimeout(5000);
        DataInputStream in = new DataInputStream(proxy.getInputStream());
        OutputStream out = proxy.getOutputStream();
        out.write(new byte[] {5, 1, 0}); out.flush();
        require(in.readUnsignedByte() == 5 && in.readUnsignedByte() == 0, "SOCKS auth");
        out.write(new byte[] {5, 1, 0, 1, 127, 0, 0, 1, 76, 28}); out.flush(); // 19484
        byte[] reply = new byte[10]; in.readFully(reply);
        require(reply[1] == 0, "SOCKS connect");
        byte[] data = new byte[8]; in.readFully(data);
        require(new String(data, "UTF-8").equals("SMOKE_OK"), "proxied bytes");
      }
      responder.join(5000); server.close();
      core.gcStop(); core.gcStop();
    }
    if (args.length > 2) {
      System.load(args[2]);
      int tun = openTun();
      require(tun >= 0, "create test TUN (requires adb root)");
      String tunConfig = "{\"env\":{\"xray.tun.fd\":\"999999\"},\"log\":{\"loglevel\":\"warning\"},\"inbounds\":[{\"protocol\":\"tun\",\"settings\":{\"name\":\"gcsmoke\",\"mtu\":1500}}],\"outbounds\":[{\"protocol\":\"freedom\"}]}";
      for (int i = 0; i < 3; i++) {
        String err = core.gcStart(tunConfig, tun);
        require(err.isEmpty(), "TUN start: " + err);
        core.gcStop();
        require(fdOpen(tun), "Java original TUN closed");
      }
      closeFd(tun);
      System.out.println("TUN_PASS: three real Android TUN start/stop cycles; stale config FD overridden; original FD retained");
    }
    System.out.println("SMOKE_PASS: JNI init/version, 30 failed starts FD ownership, 3 proxy start/stop cycles, SOCKS forwarded bytes");
  }
}
