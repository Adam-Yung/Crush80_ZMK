// Crush80 Stage 2 Flasher
//
// Uses the exact same serial framing as the mcumgr CLI (newtmgr):
// - github.com/tarm/serial for port access
// - github.com/joaojeronimo/go-crc16 for frame CRC
// - CBOR encoding via github.com/ugorji/go/codec
//
// Sends custom group 64 (flash_mgmt) commands to write MCUboot + ZMK app.
package main

import (
	"encoding/base64"
	"encoding/binary"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	crc16 "github.com/joaojeronimo/go-crc16"
	tserial "github.com/tarm/serial"
	"github.com/ugorji/go/codec"
)

const (
	mgmtGroupFlash = 64
	cmdErase       = 0
	cmdWrite       = 1
	cmdRead        = 2
	cmdCommit      = 3

	opRead  = 0
	opWrite = 2

	chunkSize      = 200
	eraseSector    = 4096
	mcubootPadSize = 0x10000
	stagingOffset  = 0x80000
	protectedStart = 0xFE000

	maxFramePayload = 127 // max base64 chars per frame line
)

type SMP struct {
	port io.ReadWriteCloser
}

func openSMP(devPath string) (*SMP, error) {
	cfg := &tserial.Config{
		Name:        devPath,
		Baud:        115200,
		ReadTimeout: 100 * time.Millisecond,
	}
	port, err := tserial.OpenPort(cfg)
	if err != nil {
		return nil, err
	}
	time.Sleep(200 * time.Millisecond)
	return &SMP{port: port}, nil
}

func (s *SMP) Close() { s.port.Close() }

// encodeFrame builds SMP serial frame(s) for a raw NMP message.
// Format (from newtmgr source):
//   First line:  [0x06][0x09][base64 up to 124 chars]\n
//   Continuation: [0x04][0x14][base64 up to 124 chars]\n
// The base64 payload encodes: [2-byte BE length][NMP msg][2-byte BE CRC16 of msg]
func (s *SMP) encodeFrame(msg []byte) []byte {
	// CRC16 of the raw NMP message
	crc := crc16.Crc16(msg)

	// Build: [length BE][msg][CRC BE]
	// length = len(msg) + 2 (includes the CRC bytes)
	fullLen := uint16(len(msg) + 2)
	pktData := make([]byte, 2+len(msg)+2)
	binary.BigEndian.PutUint16(pktData[0:2], fullLen)
	copy(pktData[2:], msg)
	binary.BigEndian.PutUint16(pktData[2+len(msg):], crc)

	// Base64 encode
	b64 := make([]byte, base64.StdEncoding.EncodedLen(len(pktData)))
	base64.StdEncoding.Encode(b64, pktData)

	// Split into lines of max 124 base64 chars
	var frame []byte
	written := 0
	for written < len(b64) {
		var hdr []byte
		if written == 0 {
			hdr = []byte{0x06, 0x09}
		} else {
			hdr = []byte{0x04, 0x14}
		}

		chunkLen := len(b64) - written
		if chunkLen > 124 {
			chunkLen = 124
		}

		frame = append(frame, hdr...)
		frame = append(frame, b64[written:written+chunkLen]...)
		frame = append(frame, '\n')
		written += chunkLen
	}
	return frame
}

// Transact sends an SMP message and reads the response.
func (s *SMP) Transact(op byte, group uint16, cmdID byte, payload map[string]interface{}) (map[string]interface{}, error) {
	// Encode CBOR payload
	var cborData []byte
	var h codec.CborHandle
	enc := codec.NewEncoderBytes(&cborData, &h)
	if err := enc.Encode(payload); err != nil {
		return nil, fmt.Errorf("cbor encode: %w", err)
	}

	// Build NMP header (8 bytes) + CBOR body
	msg := make([]byte, 8+len(cborData))
	msg[0] = op
	msg[1] = 0 // flags
	binary.BigEndian.PutUint16(msg[2:4], uint16(len(cborData)))
	binary.BigEndian.PutUint16(msg[4:6], group)
	msg[6] = 0 // seq
	msg[7] = cmdID
	copy(msg[8:], cborData)

	// Encode and send
	frame := s.encodeFrame(msg)
	if _, err := s.port.Write(frame); err != nil {
		return nil, fmt.Errorf("write: %w", err)
	}

	// Read response (collect until newline after 0x06 0x09 header)
	resp, err := s.readResponse(10 * time.Second)
	if err != nil {
		return nil, err
	}

	// Decode response
	return s.decodeResponse(resp)
}

func (s *SMP) readResponse(timeout time.Duration) ([]byte, error) {
	deadline := time.Now().Add(timeout)
	var allLines []byte
	tmp := make([]byte, 1024)
	var lineBuf []byte
	gotFirst := false

	for time.Now().Before(deadline) {
		n, err := s.port.Read(tmp)
		if n > 0 {
			lineBuf = append(lineBuf, tmp[:n]...)
			// Process complete lines
			for {
				idx := -1
				for i, b := range lineBuf {
					if b == '\n' {
						idx = i
						break
					}
				}
				if idx < 0 {
					break
				}
				line := lineBuf[:idx]
				lineBuf = lineBuf[idx+1:]

				if len(line) >= 2 && line[0] == 0x06 && line[1] == 0x09 {
					// First frame line
					allLines = append(allLines[:0], line[2:]...)
					gotFirst = true
				} else if len(line) >= 2 && line[0] == 0x04 && line[1] == 0x14 {
					// Continuation frame line
					allLines = append(allLines, line[2:]...)
				} else if gotFirst {
					// End of response (got a non-frame line after frame started)
					return allLines, nil
				}
			}
			// If we got the first frame and there's no more data coming, return
			if gotFirst && len(lineBuf) == 0 {
				// Wait a tiny bit more for continuation frames
				time.Sleep(50 * time.Millisecond)
				n2, _ := s.port.Read(tmp)
				if n2 == 0 {
					return allLines, nil
				}
				lineBuf = append(lineBuf, tmp[:n2]...)
				continue
			}
		}
		if err != nil && err != io.EOF {
			if gotFirst {
				return allLines, nil
			}
			return nil, fmt.Errorf("read: %w", err)
		}
	}
	if gotFirst {
		return allLines, nil
	}
	return nil, fmt.Errorf("timeout")
}

func (s *SMP) decodeResponse(b64Data []byte) (map[string]interface{}, error) {
	// b64Data is the concatenated base64 from all frame lines (headers already stripped)
	decoded, err := base64.StdEncoding.DecodeString(string(b64Data))
	if err != nil {
		return nil, fmt.Errorf("base64 decode: %w", err)
	}

	// Format: [2-byte BE length][NMP message][2-byte CRC]
	if len(decoded) < 4 {
		return nil, fmt.Errorf("decoded too short: %d", len(decoded))
	}
	msgLen := int(binary.BigEndian.Uint16(decoded[:2]))
	if 2+msgLen > len(decoded) {
		return nil, fmt.Errorf("msg length %d exceeds decoded size %d", msgLen, len(decoded)-2)
	}
	// msgLen includes the 2-byte CRC, so actual NMP message is msgLen-2 bytes
	msg := decoded[2 : 2+msgLen-2]

	// Skip 8-byte NMP header, decode CBOR body
	if len(msg) < 8 {
		return nil, fmt.Errorf("NMP msg too short: %d", len(msg))
	}
	cborBody := msg[8:]

	var result map[string]interface{}
	var h codec.CborHandle
	dec := codec.NewDecoderBytes(cborBody, &h)
	if err := dec.Decode(&result); err != nil {
		return nil, fmt.Errorf("cbor decode: %w", err)
	}
	return result, nil
}

// --- High-level commands ---

func (s *SMP) FlashRead(off, length uint32) ([]byte, error) {
	resp, err := s.Transact(opRead, mgmtGroupFlash, cmdRead, map[string]interface{}{
		"off": uint64(off), "len": uint64(length),
	})
	if err != nil {
		return nil, err
	}
	if rc := getRC(resp); rc != 0 {
		return nil, fmt.Errorf("rc=%d", rc)
	}
	if data, ok := resp["data"].([]byte); ok {
		return data, nil
	}
	return nil, fmt.Errorf("no data field in response")
}

func (s *SMP) FlashErase(off, length uint32) error {
	resp, err := s.Transact(opWrite, mgmtGroupFlash, cmdErase, map[string]interface{}{
		"off": uint64(off), "len": uint64(length),
	})
	if err != nil {
		return err
	}
	if rc := getRC(resp); rc != 0 {
		return fmt.Errorf("rc=%d", rc)
	}
	return nil
}

func (s *SMP) FlashWrite(off uint32, data []byte) error {
	resp, err := s.Transact(opWrite, mgmtGroupFlash, cmdWrite, map[string]interface{}{
		"off":  uint64(off),
		"data": data,
	})
	if err != nil {
		return err
	}
	if rc := getRC(resp); rc != 0 {
		return fmt.Errorf("rc=%d", rc)
	}
	return nil
}

func (s *SMP) FlashCommit(stagingOff, length uint32) error {
	resp, err := s.Transact(opWrite, mgmtGroupFlash, cmdCommit, map[string]interface{}{
		"stg": uint64(stagingOff), "len": uint64(length),
	})
	if err != nil {
		// Timeout expected — device reboots
		return nil
	}
	if rc := getRC(resp); rc != 0 {
		return fmt.Errorf("rc=%d", rc)
	}
	return nil
}

func getRC(m map[string]interface{}) int {
	if v, ok := m["rc"]; ok {
		switch val := v.(type) {
		case int64:
			return int(val)
		case uint64:
			return int(val)
		}
	}
	return 0
}

// --- Main ---

func main() {
	portFlag := flag.String("port", "/dev/cu.usbmodem1101", "Serial port")
	distFlag := flag.String("dist", "../../dist", "Dist directory")
	verifyFlag := flag.Bool("verify", true, "Verify after write")
	commitFlag := flag.Bool("commit", true, "Commit (erase+copy+reset)")
	testFlag := flag.Bool("test", false, "Test connectivity only")
	flag.Parse()

	smp, err := openSMP(*portFlag)
	if err != nil {
		die("Cannot open %s: %v", *portFlag, err)
	}
	defer smp.Close()
	fmt.Printf("Connected: %s\n", *portFlag)

	// Test
	fmt.Print("Testing flash_read(0, 4)... ")
	data, err := smp.FlashRead(0, 4)
	if err != nil {
		die("FAILED: %v", err)
	}
	fmt.Printf("OK (%02x)\n", data)

	if *testFlag {
		return
	}

	// Load firmware
	mcuboot, err := os.ReadFile(*distFlag + "/crush80-mcuboot.bin")
	if err != nil {
		die("%v", err)
	}
	app, err := os.ReadFile(*distFlag + "/crush80-zmk-app.signed.bin")
	if err != nil {
		die("%v", err)
	}

	combined := make([]byte, mcubootPadSize+len(app))
	copy(combined, mcuboot)
	for i := len(mcuboot); i < mcubootPadSize; i++ {
		combined[i] = 0xFF
	}
	copy(combined[mcubootPadSize:], app)
	eraseSize := ((len(combined) + eraseSector - 1) / eraseSector) * eraseSector

	fmt.Printf("\n  MCUboot:  %d bytes\n  App:      %d bytes\n  Combined: %d bytes\n  Staging:  0x%X..0x%X (%d KB)\n\n",
		len(mcuboot), len(app), len(combined), stagingOffset, stagingOffset+eraseSize, eraseSize/1024)

	if stagingOffset+len(combined) > protectedStart {
		die("Too large for staging")
	}

	// Erase
	fmt.Printf("Phase 1: Erasing %d KB...\n", eraseSize/1024)
	for i := 0; i < eraseSize; i += eraseSector {
		if err := smp.FlashErase(uint32(stagingOffset+i), eraseSector); err != nil {
			die("Erase 0x%X: %v", stagingOffset+i, err)
		}
		fmt.Printf("\r  %d/%d KB", (i+eraseSector)/1024, eraseSize/1024)
	}
	fmt.Println(" ✓")

	// Write
	fmt.Printf("Phase 2: Writing %d KB...\n", len(combined)/1024)
	t0 := time.Now()
	for off := 0; off < len(combined); off += chunkSize {
		end := off + chunkSize
		if end > len(combined) {
			end = len(combined)
		}
		if err := smp.FlashWrite(uint32(stagingOffset+off), combined[off:end]); err != nil {
			die("Write 0x%X: %v", stagingOffset+off, err)
		}
		fmt.Printf("\r  %d/%d KB (%.1f KB/s)", end/1024, len(combined)/1024,
			float64(end)/time.Since(t0).Seconds()/1024)
	}
	fmt.Printf(" ✓ (%.1fs)\n", time.Since(t0).Seconds())

	// Verify
	if *verifyFlag {
		fmt.Print("Phase 3: Verifying first 4 KB... ")
		vlen := 4096
		var rb []byte
		for off := 0; off < vlen; off += 256 {
			d, err := smp.FlashRead(uint32(stagingOffset+off), 256)
			if err != nil {
				die("Verify read: %v", err)
			}
			rb = append(rb, d...)
		}
		for i := range rb {
			if rb[i] != combined[i] {
				die("MISMATCH at %d: got %02x want %02x", i, rb[i], combined[i])
			}
		}
		fmt.Println("✓")
	}

	// Commit
	if !*commitFlag {
		fmt.Println("Stopping (--commit=false). Data in staging.")
		return
	}
	fmt.Println("Phase 4: Committing (3s delay)...")
	time.Sleep(3 * time.Second)
	fmt.Println("  Executing: erase 0x0 + copy + reset")
	smp.FlashCommit(uint32(stagingOffset), uint32(len(combined)))
	fmt.Println("\n  Done. Keyboard rebooting into MCUboot → ZMK.")
}

func die(f string, a ...interface{}) {
	fmt.Fprintf(os.Stderr, "ERROR: "+f+"\n", a...)
	os.Exit(1)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
