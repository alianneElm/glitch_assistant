# Glitch ESP32 — Pocket Companion Device

Waveshare ESP32-S3-Touch-AMOLED-1.75C running as a voice interface for Glitch personal assistant.

**Press button → record audio → send to Glitch backend → play response**

## Hardware

- **Board:** Waveshare ESP32-S3-Touch-AMOLED-1.75C
- **MCU:** ESP32-S3 (32MB Flash, 8MB OPI PSRAM)
- **Display:** 466x466 circular AMOLED (CO5300 driver)
- **Microphone:** ES7210 quad ADC (dual mic array)
- **Speaker:** ES8311 DAC + power amplifier (PA on GPIO 46)
- **Touch:** CST9217 capacitive touch
- **IMU:** QMI8658 accelerometer/gyroscope
- **PMU:** AXP2101 power management

## Pin Configuration

```
I2S Bus (shared mic + speaker):
  BCK   = GPIO 9
  WS    = GPIO 45
  MCLK  = GPIO 16
  DIN   = GPIO 10  (ES7210 mic data → ESP32)
  DOUT  = GPIO 8   (ESP32 → ES8311 speaker data)

I2C Bus:
  SDA   = GPIO 15
  SCL   = GPIO 14

PA Enable = GPIO 46
Button    = GPIO 0  (BOOT button, LOW = pressed)
```

## Build & Flash

Requires [PlatformIO CLI](https://platformio.org/install/cli).

```bash
cd esp32_glitch/glitch_firmware

# Compile
pio run

# Flash (ESP32 connected via USB)
pio run --target upload

# Serial monitor
pio device monitor
```

## Backend Endpoint

```
POST /esp32/voice
Headers:
  Content-Type: application/octet-stream
  X-User-ID: +46762547179
  X-Sample-Rate: 16000
  X-Channels: 1
  X-Bits: 16
Body: raw PCM audio bytes

Response:
{
  "status": "success",
  "transcript": "what user said",
  "response": "what Glitch replied",
  "audio_url": "https://..."
}
```

## Current State

- [x] WiFi connection
- [x] ES7210 microphone recording (5 seconds)
- [x] Send raw PCM to backend
- [x] Parse JSON response
- [x] ES8311 speaker initialization
- [x] Confirmation beep tones
- [ ] Full TTS audio playback (MP3 decoding)
- [ ] AMOLED display (mascot, status)
- [ ] Touch input
- [ ] Battery optimization (deep sleep)
