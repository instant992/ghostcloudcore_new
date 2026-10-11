package main

import (
	"github.com/xtls/xray-core/core"
	_ "github.com/xtls/xray-core/main/distro/all"
	"golang.org/x/net/proxy"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Exercise the same upstream runtime imported by the JNI wrapper without JNI.
func TestLocalProxyRestart(t *testing.T) {
	endpoint := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("XRAY_LOCAL_PROXY_PASS")) }))
	defer endpoint.Close()
	for i := 0; i < 3; i++ {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		port := ln.Addr().(*net.TCPAddr).Port
		ln.Close()
		text := `{"log":{"loglevel":"warning"},"inbounds":[{"listen":"127.0.0.1","port":` + strconv.Itoa(port) + `,"protocol":"socks","settings":{"auth":"noauth"}}],"outbounds":[{"protocol":"freedom"}]}`
		cfg, err := core.LoadConfig("json", strings.NewReader(text))
		if err != nil {
			t.Fatal(err)
		}
		instance, err := core.New(cfg)
		if err != nil {
			t.Fatal(err)
		}
		if err = instance.Start(); err != nil {
			instance.Close()
			t.Fatal(err)
		}
		d, err := proxy.SOCKS5("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)), nil, &net.Dialer{Timeout: 5 * time.Second})
		if err != nil {
			instance.Close()
			t.Fatal(err)
		}
		transport := &http.Transport{Dial: d.Dial}
		client := &http.Client{Transport: transport, Timeout: 10 * time.Second}
		response, err := client.Get(endpoint.URL)
		if err != nil {
			instance.Close()
			t.Fatal(err)
		}
		data, err := io.ReadAll(response.Body)
		response.Body.Close()
		transport.CloseIdleConnections()
		instance.Close()
		if err != nil || string(data) != "XRAY_LOCAL_PROXY_PASS" {
			t.Fatalf("%s %v", data, err)
		}
	}
	if _, err := core.LoadConfig("json", strings.NewReader("{bad json")); err == nil {
		t.Fatal("invalid configuration accepted")
	}
}
