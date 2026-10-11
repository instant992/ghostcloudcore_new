package main

import (
 "fmt"
 "os"
 "sync"
 "github.com/metacubex/mihomo/config"
 C "github.com/metacubex/mihomo/constant"
 "github.com/metacubex/mihomo/hub/executor"
 "github.com/metacubex/mihomo/listener"
 LC "github.com/metacubex/mihomo/listener/config"
 "github.com/metacubex/mihomo/listener/sing_tun"
 "github.com/metacubex/mihomo/tunnel"
)

var lock sync.Mutex
var activeTun *sing_tun.Listener

func initCore(home string) error {
 if home == "" { return fmt.Errorf("home-dir is empty") }
 if err := os.MkdirAll(home, 0700); err != nil { return err }
 C.SetHomeDir(home)
 return nil
}

// fd is BORROWED from VpnService: the CI sing-tun patch owns a duplicate
// and NativeTun.Close closes only that duplicate. gVisor dispatcher release
// also closes its owned stop eventfd before Attach(nil) finishes joining.
func startCore(text string, fd int) error {
 lock.Lock(); defer lock.Unlock()
 stopLocked()
 cfg, err := config.Parse([]byte(text))
 if err != nil { return err }
 opt := cfg.General.Tun
 cfg.General.Tun = LC.Tun{}
 executor.ApplyConfig(cfg, true)
 if fd >= 0 {
  opt.Enable = true
  opt.FileDescriptor = fd
  opt.AutoRoute = false
  opt.AutoDetectInterface = false
  opt.AutoRedirect = false
  activeTun, err = sing_tun.New(opt, tunnel.Tunnel)
  if err != nil { stopLocked(); return err }
 }
 return nil
}
func stopLocked() {
 if activeTun != nil { _ = activeTun.Close(); activeTun = nil }
 listener.Cleanup()
 // Applying a no-listener config closes previous proxy listeners as well.
 if cfg, err := config.Parse([]byte(`{"mode":"rule","rules":["MATCH,DIRECT"],"dns":{"enable":false},"tun":{"enable":false}}`)); err == nil { executor.ApplyConfig(cfg, true) }
}
func stopCore() { lock.Lock(); defer lock.Unlock(); stopLocked() }
func main() {}
