package main

import (
 "encoding/json"
 "io"
 "net"
 "net/http"
 "net/http/httptest"
 "os"
 "strconv"
 "testing"
 "time"
 "github.com/metacubex/mihomo/config"
 "github.com/metacubex/mihomo/component/profile/cachefile"
 "golang.org/x/net/proxy"
)
func TestGeneratedConfigs(t *testing.T) {
 data,err:=os.ReadFile("fixtures.json"); if err!=nil {t.Fatal(err)}
 var fixtures []json.RawMessage
 if err=json.Unmarshal(data,&fixtures);err!=nil {t.Fatal(err)}
 for _,raw:=range fixtures {if _,err=config.Parse(raw);err!=nil {t.Fatalf("%s: %v",raw,err)}}
}
func TestLocalProxy(t *testing.T) {
 if err:=initCore(t.TempDir());err!=nil {t.Fatal(err)}
 defer cachefile.Cache().Close()
 srv:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){w.Write([]byte("MIHOMO_LOCAL_PROXY_PASS"))}));defer srv.Close()
 ln,err:=net.Listen("tcp","127.0.0.1:0");if err!=nil {t.Fatal(err)}
 port:=ln.Addr().(*net.TCPAddr).Port;ln.Close()
 b,_:=json.Marshal(map[string]any{"mode":"rule","socks-port":port,"bind-address":"127.0.0.1","rules":[]string{"MATCH,DIRECT"},"dns":map[string]any{"enable":false},"tun":map[string]any{"enable":false}})
 if err=startCore(string(b),-1);err!=nil {t.Fatal(err)};defer stopCore()
 d,err:=proxy.SOCKS5("tcp",net.JoinHostPort("127.0.0.1",strconv.Itoa(port)),nil,&net.Dialer{Timeout:time.Second*5});if err!=nil {t.Fatal(err)}
 client:=&http.Client{Transport:&http.Transport{Dial:d.Dial},Timeout:time.Second*10}
 res,err:=client.Get(srv.URL);if err!=nil {t.Fatal(err)};defer res.Body.Close()
 body,err:=io.ReadAll(res.Body);if err!=nil || string(body)!="MIHOMO_LOCAL_PROXY_PASS" {t.Fatalf("%s %v",body,err)}
 stopCore()
 if err=startCore(string(b),-1);err!=nil {t.Fatal(err)}
 res2,err:=client.Get(srv.URL);if err!=nil {t.Fatal(err)};res2.Body.Close()
 if err=startCore("not valid yaml: [",-1);err==nil {t.Fatal("invalid config accepted")}
}
