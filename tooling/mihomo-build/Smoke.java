package expo.modules.xraycore;

import java.io.*;
import java.net.*;
import android.os.ParcelFileDescriptor;

// Runs under Android ART via app_process; no credentials or production traffic.
class GcCore {
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
  static void stage(String name) { System.out.println("GC_SMOKE_STAGE=" + name + " pid=" + android.os.Process.myPid() + " uptime_ms=" + android.os.SystemClock.elapsedRealtime()); System.out.flush(); }
  public static void main(String[] args) throws Exception {
    stage("load");
    System.load(args[0]);
    GcCore core = new GcCore();
    require(core.gcInit(args[1]).isEmpty(), "init");
    System.out.println("VERSION=" + core.gcVersion());
    require(core.gcVersion().contains("1.19.32"), "upstream version");
    stage("bad-config-begin");
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
    stage("bad-config-fd-pass");
    String config = "{\"mode\":\"rule\",\"socks-port\":19483,\"bind-address\":\"127.0.0.1\",\"rules\":[\"MATCH,DIRECT\"],\"dns\":{\"enable\":false},\"tun\":{\"enable\":false}}";
    for (int i = 0; i < 3; i++) {
      stage("proxy-start-" + i);
      require(core.gcStart(config, -1).isEmpty(), "start");
      require(core.gcStart(config, -1).isEmpty(), "replace config");
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
    stage("proxy-pass");
    if (args.length > 2) {
      stage("tun-open");
      System.load(args[2]);
      int tun = openTun(); require(tun >= 0, "real TUN creation");
      String tunConfig = "{\"mode\":\"rule\",\"rules\":[\"MATCH,DIRECT\"],\"dns\":{\"enable\":true,\"enhanced-mode\":\"fake-ip\",\"nameserver\":[\"8.8.8.8\"]},\"tun\":{\"enable\":true,\"stack\":\"gvisor\",\"auto-route\":false,\"auto-detect-interface\":false,\"inet4-address\":[\"26.26.26.1/30\"],\"dns-hijack\":[\"any:53\"]}}";
      int beforeTun = new File("/proc/self/fd").list().length;
      for (int i=0;i<10;i++) {
        stage("tun-start-" + i);
        String error = core.gcStart(tunConfig, tun);
        stage("tun-start-return-" + i + " error=" + error);
        require(error.isEmpty(), "TUN start: " + error);
        stage("tun-stop-" + i);
        core.gcStop(); require(fdOpen(tun), "borrowed TUN fd closed");
        stage("tun-fd-pass-" + i);
      }
      require(new File("/proc/self/fd").list().length <= beforeTun + 3, "TUN fd leak");
      closeFd(tun);
      System.out.println("REAL_TUN_BORROW_RESTART_PASS");
    }
    System.out.println("MIHOMO_JNI_PROXY_SMOKE_PASS");
  }
}
