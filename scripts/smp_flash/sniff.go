//go:build ignore

package main

import (
	"fmt"
	"os"
	"os/exec"
	"time"

	tserial "github.com/tarm/serial"
)

func main() {
	// Open real port
	cfg := &tserial.Config{Name: "/dev/cu.usbmodem1101", Baud: 115200, ReadTimeout: time.Second}
	port, err := tserial.OpenPort(cfg)
	if err != nil { fmt.Println("port:", err); return }
	defer port.Close()

	// Create PTY - can't easily do this in Go cross-platform
	// Instead, let's just send what we THINK is right and hex-dump the exchange
	
	// Build an echo request manually matching mcumgr format
	// mcumgr echo sends: op=2(write), group=0(OS), cmd=0(echo), payload={"d":"test"}
	// But we want flash_read: op=0(read), group=64, cmd=2, payload={"off":0,"len":4}
	
	// Let me just hex-dump what our encodeFrame produces vs what works
	fmt.Println("Sending echo via mcumgr CLI and capturing output...")
	port.Close()
	
	// Run mcumgr and capture its serial traffic by using socat
	// Actually, just run mcumgr and see what it does by timing
	cmd := exec.Command(os.ExpandEnv("$HOME/go/bin/mcumgr"),
		"--conntype", "serial",
		"--connstring", "dev=/dev/cu.usbmodem1101,baud=115200",
		"echo", "x")
	out, err := cmd.CombinedOutput()
	fmt.Printf("mcumgr output: %s (err: %v)\n", out, err)
}
