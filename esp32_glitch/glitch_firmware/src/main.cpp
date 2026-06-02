/**
 * Glitch ESP32 Firmware — Phase 5 (Face Edition)
 *
 * Waveshare ESP32-S3-Touch-AMOLED-1.75C
 * Press button → record audio → send to Glitch backend → play TTS → show response
 * Full-screen cyberpunk face with animated state overlays.
 *
 * Hardware:
 *   - ES7210: 4-channel ADC (microphone input)
 *   - ES8311: DAC (speaker output)
 *   - PA (GPIO 46): Power amplifier enable
 *   - I2S bus shared: BCK=9, WS=45, MCLK=16, DIN=10, DOUT=8
 *   - CO5300: 466x466 AMOLED (QSPI)
 *   - AXP2101: PMU (battery + charging management)
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include "Arduino_GFX_Library.h"
#include "pin_config.h"
#include "es7210.h"
#include "audio_hal.h"
#include "es8311_speaker.h"
#include "glitch_face.h"

#define XPOWERS_CHIP_AXP2101
#include "XPowersLib.h"

// ==================== CONFIG ====================
const char* GLITCH_URL = "https://alluring-courtesy-production-9b65.up.railway.app";
const char* USER_ID    = "+46762547179";

// Known WiFi networks — tried in order, first found wins
struct WifiNetwork { const char* ssid; const char* password; };
static const WifiNetwork WIFI_NETWORKS[] = {
    { "TP-Link_D9F7", "42209317"    },  // Home
    { "iPhone de Alianne", "angelica2010" },  // Mobile hotspot
};
static const int WIFI_NETWORK_COUNT = sizeof(WIFI_NETWORKS) / sizeof(WIFI_NETWORKS[0]);

// Audio settings
#define SAMPLE_RATE     16000
#define RECORD_SECONDS  10
#define I2S_CH          I2S_NUM_1
#define BUFFER_SIZE     1024
#define SPEAKER_VOLUME  85

// Voice Activity Detection (VAD) — stop recording on silence
#define VAD_MIN_RECORD_MS   2000   // Minimum recording time before VAD kicks in
#define VAD_SILENCE_MS      1500   // Stop after this much silence
#define VAD_THRESHOLD       200    // Amplitude threshold for "speech" (raw TDM avg ~370 during speech)
#define VAD_WINDOW_SAMPLES  1600   // ~100ms window for energy calculation

// Button
#define BUTTON_PIN      0  // Small button (BOOT)

// ==================== DISPLAY ====================
Arduino_DataBus *bus = new Arduino_ESP32QSPI(
    LCD_CS, LCD_SCLK, LCD_SDIO0, LCD_SDIO1, LCD_SDIO2, LCD_SDIO3);
Arduino_CO5300 *gfx = new Arduino_CO5300(
    bus, LCD_RESET, 0 /* rotation */, LCD_WIDTH, LCD_HEIGHT, 6, 0, 0, 0);

// ==================== GLOBALS ====================
bool recording = false;
bool wifi_connected = false;
bool speaker_ready = false;
bool display_ready = false;

// PMU (battery management)
XPowersPMU PMU;
bool pmu_ready = false;
unsigned long last_battery_update = 0;
#define BATTERY_UPDATE_MS 5000  // Update battery every 5 seconds

// (removed last_charge_percent — using voltage/charger-state approach instead)

unsigned long last_wifi_retry = 0;
#define WIFI_RETRY_MS 30000  // Retry WiFi every 30 seconds when disconnected

// Reminder polling
unsigned long last_reminder_check = 0;
#define REMINDER_CHECK_MS 30000  // Check for reminders every 30 seconds

// ==================== DISPLAY ====================

void setup_display() {
    Serial.println("[GLITCH] Initializing AMOLED display...");
    if (!gfx->begin()) {
        Serial.println("[GLITCH] Display init failed!");
        return;
    }
    display_ready = true;
    gfx->fillScreen(0x0000);
    gfx->setBrightness(200);
    Serial.println("[GLITCH] Display ready (466x466 AMOLED)");

    // Initialize face system
    face_init(gfx);
    face_set_state(STATE_BOOT);
}

// ==================== PMU (AXP2101) ====================

// Read battery voltage directly from AXP2101 ADC result registers 0x34+0x35.
// getBattVoltage() calls isBatteryConnect() which reads STATUS1 — broken on this board.
// Format: ((reg0x34 & 0x1F) << 8) | reg0x35, 1 mV per LSB.
int read_raw_battery_voltage_mv() {
    Wire.beginTransmission((uint8_t)0x34);
    Wire.write((uint8_t)0x34);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)0x34, (uint8_t)2);
    if (Wire.available() >= 2) {
        uint8_t h = Wire.read();
        uint8_t l = Wire.read();
        return ((h & 0x1F) << 8) | l;
    }
    return -1;
}

// Read battery SOC from register 0xA4 — also bypasses isBatteryConnect().
// Returns 0-100, or -1 on read error. Note: AXP2101 may report 0 when
// battery detection is broken; use only to confirm, not as sole source.
int read_raw_battery_percent() {
    Wire.beginTransmission((uint8_t)0x34);
    Wire.write((uint8_t)0xA4);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)0x34, (uint8_t)1);
    if (Wire.available()) {
        return Wire.read();
    }
    return -1;
}

void setup_pmu() {
    Serial.println("[GLITCH] Initializing AXP2101 PMU...");

    if (PMU.begin(Wire, AXP2101_SLAVE_ADDRESS, IIC_SDA, IIC_SCL)) {
        pmu_ready = true;
        Serial.println("[GLITCH] PMU initialized");

        // Enable battery detection — needed for charging and battery power!
        PMU.enableBattDetection();

        // Disable TS pin — no thermistor on this board.
        // Without this, charger reports "abnormal" and won't charge.
        PMU.disableTSPinMeasure();

        // Charge settings: 400mA constant current, 4.2V target
        PMU.setChargerConstantCurr(XPOWERS_AXP2101_CHG_CUR_400MA);
        PMU.setChargeTargetVoltage(XPOWERS_AXP2101_CHG_VOL_4V2);

        // Enable ADC measurements
        PMU.enableBattVoltageMeasure();
        PMU.enableVbusVoltageMeasure();
        PMU.enableSystemVoltageMeasure();

        // Wait for ADC to settle
        delay(300);

        // Detailed PMU diagnostic at boot
        int sys_v = PMU.getSystemVoltage();
        int vbus_v = PMU.getVbusVoltage();
        bool usb = PMU.isVbusIn();
        bool batt_det = PMU.isBatteryConnect();
        uint8_t cs = PMU.getChargerStatus();
        int raw_batt_v = read_raw_battery_voltage_mv();

        Serial.println("[PMU] === Battery Diagnostic ===");
        Serial.printf("[PMU]   System voltage:  %d mV\n", sys_v);
        Serial.printf("[PMU]   VBUS voltage:    %d mV\n", vbus_v);
        Serial.printf("[PMU]   Raw BATT ADC:    %d mV\n", raw_batt_v);
        Serial.printf("[PMU]   USB connected:   %s\n", usb ? "YES" : "NO");
        Serial.printf("[PMU]   Battery detect:  %s\n", batt_det ? "YES" : "NO");
        Serial.printf("[PMU]   Charger state:   %d (%s)\n", cs,
                      cs==0?"trickle":cs==1?"pre":cs==2?"CC":cs==3?"CV":cs==4?"done":"idle");

        // Raw register dump for debugging
        Wire.beginTransmission(0x34);
        Wire.write(0x00);  // STATUS1
        Wire.endTransmission(false);
        Wire.requestFrom((uint8_t)0x34, (uint8_t)3);
        if (Wire.available() >= 3) {
            uint8_t s1 = Wire.read();
            uint8_t s2 = Wire.read();
            uint8_t s3 = Wire.read();
            Serial.printf("[PMU]   STATUS1=0x%02X STATUS2=0x%02X STATUS3=0x%02X\n", s1, s2, s3);
            Serial.printf("[PMU]   STATUS1 bits: VBUS_in=%d BattPresent=%d\n",
                          (s1>>5)&1, (s1>>3)&1);
        }
        Serial.println("[PMU] =============================");
    } else {
        Serial.println("[GLITCH] PMU init failed — battery monitoring disabled");
    }
}

void update_battery() {
    if (!pmu_ready) return;

    unsigned long now = millis();
    if (now - last_battery_update < BATTERY_UPDATE_MS) return;
    last_battery_update = now;

    BatteryInfo info;
    info.usb_in = PMU.isVbusIn();
    info.charge_state = PMU.getChargerStatus();

    // Use system voltage — most reliable on this board.
    // getBattVoltage() depends on isBatteryConnect() which is broken.
    info.voltage_mv = PMU.getSystemVoltage();

    // Charging: USB connected + charger in active state (trickle/pre/CC/CV)
    info.charging = info.usb_in && (info.charge_state < 4);

    // Estimate percent from system voltage using LiPo discharge curve.
    // On this board, getSystemVoltage() returns battery-level voltage (~3.7V)
    // even when USB is connected, so we can always use it.
    int v = info.voltage_mv;

    if (v >= 4150) {
        info.percent = 95 + (v - 4150) * 5 / 50;
    } else if (v >= 3900) {
        info.percent = 70 + (v - 3900) * 25 / 250;
    } else if (v >= 3700) {
        info.percent = 40 + (v - 3700) * 30 / 200;
    } else if (v >= 3500) {
        info.percent = 15 + (v - 3500) * 25 / 200;
    } else if (v >= 3200) {
        info.percent = (v - 3200) * 15 / 300;
    } else if (v > 2800) {
        info.percent = 0;
    } else {
        info.percent = -1;  // No battery detected
    }
    if (info.percent >= 0) info.percent = constrain(info.percent, 0, 100);

    Serial.printf("[BATT] sysV=%dmV usb=%s cs=%d pct=%d%%\n",
                  v, info.usb_in ? "Y" : "N",
                  info.charge_state, info.percent);
    face_set_battery(info);
}

// ==================== WIFI ====================

// Scan visible networks and return the index of the first known one, or -1.
static int wifi_find_known_network() {
    Serial.println("[WIFI] Scanning...");
    int found = WiFi.scanNetworks(false, false, false, 300);
    if (found <= 0) {
        Serial.println("[WIFI] No networks found");
        WiFi.scanDelete();
        return -1;
    }
    for (int k = 0; k < WIFI_NETWORK_COUNT; k++) {
        for (int i = 0; i < found; i++) {
            if (WiFi.SSID(i) == WIFI_NETWORKS[k].ssid) {
                Serial.printf("[WIFI] Found: %s (RSSI %d)\n",
                              WIFI_NETWORKS[k].ssid, WiFi.RSSI(i));
                WiFi.scanDelete();
                return k;
            }
        }
    }
    WiFi.scanDelete();
    return -1;
}

// Try to connect to one specific network. Returns true on success.
static bool wifi_connect_to(int idx) {
    Serial.printf("[WIFI] Connecting to %s...", WIFI_NETWORKS[idx].ssid);
    WiFi.begin(WIFI_NETWORKS[idx].ssid, WIFI_NETWORKS[idx].password);
    for (int t = 0; t < 20; t++) {
        if (WiFi.status() == WL_CONNECTED) {
            Serial.printf(" OK  IP: %s\n", WiFi.localIP().toString().c_str());
            return true;
        }
        delay(500);
        Serial.print(".");
    }
    Serial.println(" timeout");
    WiFi.disconnect(true);
    return false;
}

void setup_wifi() {
    WiFi.mode(WIFI_STA);
    int idx = wifi_find_known_network();
    if (idx >= 0) {
        wifi_connected = wifi_connect_to(idx);
    }
    if (!wifi_connected) {
        Serial.println("[WIFI] No known network available — continuing offline");
    }
}

// Try to reconnect: scan for any known network and connect to it.
// Called from loop() when connection is lost.
static void wifi_reconnect() {
    WiFi.disconnect(true);
    delay(200);
    int idx = wifi_find_known_network();
    if (idx >= 0) {
        wifi_connected = wifi_connect_to(idx);
        if (wifi_connected) face_set_wifi(true);
    }
}

// ==================== I2S MANAGEMENT ====================

void i2s_install_rx() {
    // I2S config for microphone input (ES7210)
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ALL_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 64,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0,
        .mclk_multiple = I2S_MCLK_MULTIPLE_256,
        .bits_per_chan = I2S_BITS_PER_CHAN_16BIT,
        .chan_mask = (i2s_channel_t)(I2S_TDM_ACTIVE_CH0 | I2S_TDM_ACTIVE_CH1),
    };

    i2s_pin_config_t pin_config = {0};
    pin_config.bck_io_num = PIN_ES7210_BCLK;
    pin_config.ws_io_num = PIN_ES7210_LRCK;
    pin_config.data_in_num = PIN_ES7210_DIN;
    pin_config.data_out_num = -1;
    pin_config.mck_io_num = PIN_ES7210_MCLK;

    i2s_driver_install(I2S_CH, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_CH, &pin_config);
    i2s_zero_dma_buffer(I2S_CH);
}

void i2s_install_tx() {
    // I2S config for speaker output (ES8311) — stereo format
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 256,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0,
        .mclk_multiple = I2S_MCLK_MULTIPLE_256,
        .bits_per_chan = I2S_BITS_PER_CHAN_16BIT,
    };

    i2s_pin_config_t pin_config = {0};
    pin_config.bck_io_num = PIN_ES7210_BCLK;
    pin_config.ws_io_num = PIN_ES7210_LRCK;
    pin_config.data_in_num = -1;
    pin_config.data_out_num = PIN_ES8311_DOUT;
    pin_config.mck_io_num = PIN_ES7210_MCLK;

    i2s_driver_install(I2S_CH, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_CH, &pin_config);
    i2s_zero_dma_buffer(I2S_CH);
}

// ==================== MICROPHONE (ES7210) ====================
void setup_microphone() {
    Serial.println("[GLITCH] Initializing ES7210 microphone...");

    audio_hal_codec_config_t cfg = {
        .adc_input = AUDIO_HAL_ADC_INPUT_ALL,
        .codec_mode = AUDIO_HAL_CODEC_MODE_ENCODE,
        .i2s_iface = {
            .mode = AUDIO_HAL_MODE_SLAVE,
            .fmt = AUDIO_HAL_I2S_NORMAL,
            .samples = AUDIO_HAL_16K_SAMPLES,
            .bits = AUDIO_HAL_BIT_LENGTH_16BITS,
        },
    };

    es7210_adc_init(&Wire, &cfg);
    es7210_adc_config_i2s(cfg.codec_mode, &cfg.i2s_iface);
    es7210_adc_set_gain(
        (es7210_input_mics_t)(ES7210_INPUT_MIC1 | ES7210_INPUT_MIC2),
        (es7210_gain_value_t)GAIN_37_5DB
    );
    es7210_adc_set_gain(
        (es7210_input_mics_t)(ES7210_INPUT_MIC3 | ES7210_INPUT_MIC4),
        (es7210_gain_value_t)GAIN_37_5DB
    );
    es7210_adc_ctrl_state(cfg.codec_mode, AUDIO_HAL_CTRL_START);

    // Install I2S in RX mode (default state = listening)
    i2s_install_rx();

    Serial.println("[GLITCH] Microphone ready");
}

// ==================== SPEAKER (ES8311) ====================
void setup_speaker() {
    Serial.println("[GLITCH] Initializing ES8311 speaker...");
    speaker_ready = es8311_speaker_init(SAMPLE_RATE, SPEAKER_VOLUME);
    if (speaker_ready) {
        Serial.println("[GLITCH] Speaker ready");
    } else {
        Serial.println("[GLITCH] Speaker init failed — continuing without audio output");
    }
}

// ==================== I2S WRITE HELPER ====================
// Write mono samples as stereo (duplicate L→R) for ES8311
void i2s_write_mono_as_stereo(const int16_t* mono, int num_samples) {
    int16_t stereo[512];  // 256 stereo pairs
    size_t bytes_written;
    int offset = 0;
    while (offset < num_samples) {
        int chunk = min(256, num_samples - offset);
        for (int i = 0; i < chunk; i++) {
            stereo[i * 2]     = mono[offset + i];  // Left
            stereo[i * 2 + 1] = mono[offset + i];  // Right
        }
        i2s_write(I2S_CH, (char*)stereo, chunk * 2 * sizeof(int16_t), &bytes_written, portMAX_DELAY);
        offset += chunk;
    }
}

// ==================== BEEP TONE ====================
void play_beep(int freq_hz, int duration_ms) {
    if (!speaker_ready) return;

    Serial.printf("[GLITCH] Playing beep: %d Hz, %d ms\n", freq_hz, duration_ms);

    // Switch I2S to TX mode
    i2s_driver_uninstall(I2S_CH);
    i2s_install_tx();

    // Generate sine wave tone
    int total_samples = (SAMPLE_RATE * duration_ms) / 1000;
    int chunk_size = 256;
    int16_t* buf = (int16_t*)malloc(chunk_size * sizeof(int16_t));
    if (!buf) {
        Serial.println("[GLITCH] Beep: malloc failed");
        i2s_driver_uninstall(I2S_CH);
        i2s_install_rx();
        return;
    }

    float phase = 0.0f;
    float phase_inc = 2.0f * PI * freq_hz / SAMPLE_RATE;
    int samples_written = 0;
    size_t bytes_written;

    while (samples_written < total_samples) {
        int to_write = min(chunk_size, total_samples - samples_written);
        for (int i = 0; i < to_write; i++) {
            float env = 1.0f;
            int fade_samples = SAMPLE_RATE / 20;
            if (samples_written + i < fade_samples) {
                env = (float)(samples_written + i) / fade_samples;
            } else if (total_samples - (samples_written + i) < fade_samples) {
                env = (float)(total_samples - (samples_written + i)) / fade_samples;
            }
            buf[i] = (int16_t)(sinf(phase) * 16000.0f * env);
            phase += phase_inc;
            if (phase >= 2.0f * PI) phase -= 2.0f * PI;
        }
        i2s_write_mono_as_stereo(buf, to_write);
        samples_written += to_write;
    }

    // Flush with silence
    memset(buf, 0, chunk_size * sizeof(int16_t));
    i2s_write_mono_as_stereo(buf, chunk_size);

    free(buf);

    // Switch back to RX mode
    i2s_driver_uninstall(I2S_CH);
    i2s_install_rx();
}

// Glitch signature sound: two-tone chirp
void play_glitch_beep() {
    if (!speaker_ready) return;

    // Switch to TX once for the whole sequence
    i2s_driver_uninstall(I2S_CH);
    i2s_install_tx();

    int tones[] = {880, 1100};
    int durations[] = {100, 150};
    int chunk_size = 256;
    int16_t* buf = (int16_t*)malloc(chunk_size * sizeof(int16_t));
    if (!buf) {
        i2s_driver_uninstall(I2S_CH);
        i2s_install_rx();
        return;
    }

    size_t bytes_written;

    for (int t = 0; t < 2; t++) {
        int total_samples = (SAMPLE_RATE * durations[t]) / 1000;
        float phase = 0.0f;
        float phase_inc = 2.0f * PI * tones[t] / SAMPLE_RATE;
        int samples_written = 0;

        while (samples_written < total_samples) {
            int to_write = min(chunk_size, total_samples - samples_written);
            for (int i = 0; i < to_write; i++) {
                float env = 1.0f;
                int fade = SAMPLE_RATE / 50;
                if (samples_written + i < fade)
                    env = (float)(samples_written + i) / fade;
                else if (total_samples - (samples_written + i) < fade)
                    env = (float)(total_samples - (samples_written + i)) / fade;
                buf[i] = (int16_t)(sinf(phase) * 14000.0f * env);
                phase += phase_inc;
                if (phase >= 2.0f * PI) phase -= 2.0f * PI;
            }
            i2s_write_mono_as_stereo(buf, to_write);
            samples_written += to_write;
        }

        // Small gap between tones
        if (t == 0) {
            memset(buf, 0, chunk_size * sizeof(int16_t));
            i2s_write_mono_as_stereo(buf, chunk_size);
        }
    }

    // Flush silence
    memset(buf, 0, chunk_size * sizeof(int16_t));
    i2s_write_mono_as_stereo(buf, chunk_size);

    free(buf);

    // Back to RX
    i2s_driver_uninstall(I2S_CH);
    i2s_install_rx();
}

// ==================== PLAY PCM FROM URL (STREAMING) ====================
void play_pcm_url(const char* url) {
    if (!speaker_ready || strlen(url) == 0) return;

    unsigned long t_start = millis();
    Serial.printf("[GLITCH] Streaming audio: %s\n", url);
    face_set_state(STATE_SPEAKING);

    // Ensure PA is enabled
    digitalWrite(PA, HIGH);

    HTTPClient http;
    http.begin(url);
    http.setTimeout(15000);
    int httpCode = http.GET();

    if (httpCode != 200) {
        Serial.printf("[GLITCH] Audio download failed: %d\n", httpCode);
        http.end();
        return;
    }

    int contentLen = http.getSize();
    Serial.printf("[GLITCH] Audio size: %d bytes\n", contentLen);

    WiFiClient* stream = http.getStreamPtr();

    // Read WAV header first (44 bytes)
    uint8_t wav_header[44];
    int hdr_read = 0;
    unsigned long timeout_start = millis();
    while (hdr_read < 44 && (millis() - timeout_start) < 5000) {
        int avail = stream->available();
        if (avail > 0) {
            int to_read = min(avail, 44 - hdr_read);
            int got = stream->readBytes(wav_header + hdr_read, to_read);
            hdr_read += got;
            timeout_start = millis();
        } else {
            delay(1);
        }
    }

    bool has_wav = (hdr_read >= 44 &&
                    wav_header[0] == 'R' && wav_header[1] == 'I' &&
                    wav_header[2] == 'F' && wav_header[3] == 'F');

    int wav_sample_rate = SAMPLE_RATE;
    int wav_channels = 1;
    if (has_wav) {
        wav_sample_rate = wav_header[24] | (wav_header[25] << 8) |
                          (wav_header[26] << 16) | (wav_header[27] << 24);
        wav_channels = wav_header[22] | (wav_header[23] << 8);
        Serial.printf("[GLITCH] WAV: %d Hz, %d ch\n", wav_sample_rate, wav_channels);
    }

    // Switch I2S to TX with matching sample rate
    i2s_driver_uninstall(I2S_CH);

    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = (uint32_t)wav_sample_rate,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 256,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0,
        .mclk_multiple = I2S_MCLK_MULTIPLE_256,
        .bits_per_chan = I2S_BITS_PER_CHAN_16BIT,
    };

    i2s_pin_config_t pin_config = {0};
    pin_config.bck_io_num = PIN_ES7210_BCLK;
    pin_config.ws_io_num = PIN_ES7210_LRCK;
    pin_config.data_in_num = -1;
    pin_config.data_out_num = PIN_ES8311_DOUT;
    pin_config.mck_io_num = PIN_ES7210_MCLK;

    i2s_driver_install(I2S_CH, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_CH, &pin_config);
    i2s_zero_dma_buffer(I2S_CH);

    unsigned long t_first_play = millis();
    Serial.printf("[GLITCH] Time to first audio: %lu ms\n", t_first_play - t_start);

    // Stream playback — read chunks and play immediately
    int16_t read_buf[512];  // Read buffer
    int total_played = 0;
    int bytes_remaining = contentLen - (has_wav ? 44 : 0);

    // If header wasn't WAV, play those 44 bytes as PCM
    if (!has_wav && hdr_read > 0) {
        int16_t* hdr_pcm = (int16_t*)wav_header;
        int hdr_samples = hdr_read / sizeof(int16_t);
        if (wav_channels == 1) {
            i2s_write_mono_as_stereo(hdr_pcm, hdr_samples);
        } else {
            size_t bw;
            i2s_write(I2S_CH, (char*)hdr_pcm, hdr_read, &bw, portMAX_DELAY);
        }
        total_played += hdr_samples;
    }

    timeout_start = millis();
    while ((stream->connected() || stream->available()) && bytes_remaining > 0) {
        int avail = stream->available();
        if (avail > 0) {
            int to_read = min(avail, (int)sizeof(read_buf));
            to_read = min(to_read, bytes_remaining);
            int got = stream->readBytes((uint8_t*)read_buf, to_read);
            bytes_remaining -= got;

            int samples = got / sizeof(int16_t);
            if (wav_channels == 1) {
                i2s_write_mono_as_stereo(read_buf, samples);
            } else {
                // Stereo — send directly
                size_t bw;
                i2s_write(I2S_CH, (char*)read_buf, got, &bw, portMAX_DELAY);
            }
            total_played += samples;
            timeout_start = millis();
        } else {
            delay(1);
            if (millis() - timeout_start > 5000) break;
        }
    }
    http.end();

    // Flush with silence
    int16_t silence[256] = {0};
    i2s_write_mono_as_stereo(silence, 256);
    delay(100);

    unsigned long t_end = millis();
    Serial.printf("[GLITCH] Streamed %d samples in %lu ms (first audio at +%lu ms)\n",
                  total_played, t_end - t_start, t_first_play - t_start);

    // Switch back to RX at original sample rate
    i2s_driver_uninstall(I2S_CH);
    i2s_install_rx();
}

// ==================== REMINDER POLLING ====================
void check_reminders() {
    if (!wifi_connected) return;

    unsigned long now = millis();
    if (now - last_reminder_check < REMINDER_CHECK_MS) return;
    last_reminder_check = now;

    HTTPClient http;
    String url = String(GLITCH_URL) + "/esp32/reminders";
    http.begin(url);
    http.addHeader("X-User-ID", USER_ID);
    http.setTimeout(10000);

    int httpCode = http.GET();
    if (httpCode != 200) {
        http.end();
        return;
    }

    String response = http.getString();
    http.end();

    // Parse JSON
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, response);
    if (err) return;

    const char* status = doc["status"] | "none";
    if (strcmp(status, "reminder") != 0) return;

    // We have a reminder!
    const char* text = doc["text"] | "";
    const char* pcm_url = doc["pcm_url"] | "";

    Serial.printf("[REMINDER] %s\n", text);

    // Show reminder on screen
    face_show_response("Recordatorio:", text);

    // Play notification sound
    play_beep(880, 150);
    delay(100);
    play_beep(1100, 150);

    // Play TTS audio if available
    if (strlen(pcm_url) > 0) {
        play_pcm_url(pcm_url);
    }

    // Show for a few seconds, then return to idle
    delay(5000);
    face_set_state(STATE_IDLE);
}

// ==================== RECORD + SEND ====================
void record_and_send() {
    if (!wifi_connected) {
        Serial.println("[GLITCH] No WiFi — cannot send audio");
        face_set_state(STATE_ERROR);
        play_beep(200, 500);
        delay(2000);
        face_set_state(STATE_IDLE);
        return;
    }

    // Recording start beep
    face_set_state(STATE_LISTENING);
    play_beep(660, 100);

    Serial.println("[GLITCH] Recording...");
    recording = true;

    // Allocate buffer in PSRAM for audio data
    // TDM gives 2 interleaved channels, so we need 2x the samples
    int total_samples = SAMPLE_RATE * RECORD_SECONDS * 2;
    int total_bytes = total_samples * sizeof(int16_t);
    int16_t* audio_buffer = (int16_t*)ps_malloc(total_bytes);

    if (!audio_buffer) {
        Serial.println("[GLITCH] Failed to allocate audio buffer!");
        recording = false;
        return;
    }

    // Record audio with VAD (Voice Activity Detection)
    int offset = 0;
    size_t bytes_read;
    unsigned long start_time = millis();
    unsigned long last_voice_time = millis();  // Last time speech was detected
    bool vad_stopped = false;

    while (offset < total_samples && (millis() - start_time) < (RECORD_SECONDS * 1000 + 500)) {
        int to_read = min(BUFFER_SIZE, total_samples - offset);
        i2s_read(I2S_CH, (char*)(audio_buffer + offset), to_read * sizeof(int16_t), &bytes_read, portMAX_DELAY);
        int samples_got = bytes_read / sizeof(int16_t);

        // Calculate energy of this chunk for VAD
        int64_t energy = 0;
        for (int i = 0; i < samples_got; i++) {
            energy += abs(audio_buffer[offset + i]);
        }
        int avg_energy = (samples_got > 0) ? (int)(energy / samples_got) : 0;

        if (avg_energy > VAD_THRESHOLD) {
            last_voice_time = millis();
        }

        offset += samples_got;

        // Check VAD: if past minimum time and silence detected for VAD_SILENCE_MS
        unsigned long elapsed = millis() - start_time;
        if (elapsed > VAD_MIN_RECORD_MS && (millis() - last_voice_time) > VAD_SILENCE_MS) {
            vad_stopped = true;
            Serial.printf("[GLITCH] VAD: silence detected, stopping after %lu ms\n", elapsed);
            break;
        }
    }

    unsigned long record_time = millis() - start_time;
    Serial.printf("[GLITCH] Recorded %d raw samples (%d bytes, 2-ch TDM) in %lu ms%s\n",
                  offset, offset * 2, record_time, vad_stopped ? " (VAD)" : "");
    recording = false;

    // Audio diagnostics — check if mic is capturing real signal
    int16_t min_val = 32767, max_val = -32768;
    int64_t sum = 0;
    int nonzero = 0;
    for (int i = 0; i < offset; i++) {
        int16_t s = audio_buffer[i];
        if (s < min_val) min_val = s;
        if (s > max_val) max_val = s;
        sum += abs(s);
        if (s != 0) nonzero++;
    }
    int avg = (offset > 0) ? (int)(sum / offset) : 0;
    Serial.printf("[GLITCH] Audio stats (raw): min=%d max=%d avg=%d nonzero=%d/%d\n",
                  min_val, max_val, avg, nonzero, offset);

    // Check CH0 vs CH1 to find which has voice data
    int64_t sum_ch0 = 0, sum_ch1 = 0;
    for (int i = 0; i < offset - 1; i += 2) {
        sum_ch0 += abs(audio_buffer[i]);
        sum_ch1 += abs(audio_buffer[i + 1]);
    }
    int half = offset / 2;
    Serial.printf("[GLITCH] CH0 avg=%d, CH1 avg=%d\n",
                  half > 0 ? (int)(sum_ch0 / half) : 0,
                  half > 0 ? (int)(sum_ch1 / half) : 0);

    // Extract mono from interleaved TDM data (keep CH0, skip CH1)
    int mono_samples = offset / 2;
    for (int i = 0; i < mono_samples; i++) {
        audio_buffer[i] = audio_buffer[i * 2];  // Keep every other sample (CH0)
    }
    offset = mono_samples;
    Serial.printf("[GLITCH] Extracted mono: %d samples (%d bytes)\n", offset, offset * 2);

    // Recording end beep
    play_beep(880, 100);

    // Send to backend
    face_set_state(STATE_THINKING);
    Serial.println("[GLITCH] Sending to backend...");

    HTTPClient http;
    String url = String(GLITCH_URL) + "/esp32/voice";
    http.begin(url);
    http.addHeader("Content-Type", "application/octet-stream");
    http.addHeader("X-User-ID", USER_ID);
    http.addHeader("X-Sample-Rate", String(SAMPLE_RATE));
    http.addHeader("X-Channels", "1");
    http.addHeader("X-Bits", "16");
    http.setTimeout(30000);

    int httpCode = http.POST((uint8_t*)audio_buffer, offset * sizeof(int16_t));

    if (httpCode == 200) {
        String response = http.getString();
        Serial.printf("[GLITCH] Backend response: %s\n", response.c_str());

        // Parse JSON response
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, response);

        if (!err) {
            const char* status = doc["status"] | "error";
            const char* transcript = doc["transcript"] | "";
            const char* reply = doc["response"] | "";
            const char* audio_url = doc["audio_url"] | "";
            const char* pcm_url = doc["pcm_url"] | "";

            Serial.println("=== GLITCH RESPONSE ===");
            Serial.printf("  Status:     %s\n", status);
            Serial.printf("  You said:   %s\n", transcript);
            Serial.printf("  Glitch:     %s\n", reply);
            Serial.printf("  audio_url:  '%s'\n", audio_url);
            Serial.printf("  pcm_url:    '%s'\n", pcm_url);
            Serial.printf("  pcm_url len: %d\n", strlen(pcm_url));
            Serial.println("=======================");

            // Success feedback
            if (strcmp(status, "success") == 0) {
                face_show_response(transcript, reply);

                // Play TTS audio if available, otherwise just beep
                if (strlen(pcm_url) > 0) {
                    face_set_state(STATE_SPEAKING);
                    play_pcm_url(pcm_url);
                } else {
                    play_glitch_beep();
                }
            } else {
                face_set_state(STATE_ERROR);
                play_beep(330, 300);
            }
        } else {
            Serial.printf("[GLITCH] JSON parse error: %s\n", err.c_str());
            play_beep(330, 300);
        }
    } else {
        Serial.printf("[GLITCH] Backend error: %d\n", httpCode);
        if (httpCode > 0) {
            Serial.printf("[GLITCH] Response: %s\n", http.getString().c_str());
        }
        face_set_state(STATE_ERROR);
        play_beep(220, 500);
    }

    http.end();
    free(audio_buffer);

    // Show result for a few seconds, then return to idle face
    delay(5000);
    face_set_state(STATE_IDLE);

    Serial.println("[GLITCH] Ready for next command");
}

// ==================== SETUP ====================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("========================================");
    Serial.println("  Glitch ESP32 — Phase 5 (Face)");
    Serial.println("  Waveshare ESP32-S3-AMOLED-1.75C");
    Serial.println("========================================");
    Serial.printf("PSRAM: %d KB\n", ESP.getPsramSize() / 1024);
    Serial.printf("Flash: %d KB\n", ESP.getFlashChipSize() / 1024);

    // Button setup
    pinMode(BUTTON_PIN, INPUT);

    // Power amplifier enable
    pinMode(PA, OUTPUT);
    digitalWrite(PA, HIGH);

    // I2C bus (shared by ES7210 + ES8311 + touch)
    Wire.begin(IIC_SDA, IIC_SCL);
    delay(200);

    // Initialize display first (visual feedback during boot)
    setup_display();
    // face_init + STATE_BOOT done inside setup_display()

    // Connect WiFi
    setup_wifi();
    face_set_wifi(wifi_connected);

    // Initialize PMU (battery monitoring)
    setup_pmu();

    // Initialize audio codecs
    setup_microphone();
    setup_speaker();

    // Boot chime
    play_glitch_beep();

    // Initial battery read
    update_battery();

    // Transition to idle — face with animated overlays
    face_set_state(STATE_IDLE);

    Serial.println("\n[GLITCH] Ready! Press button to talk.");
}

// ==================== LOOP ====================
void loop() {
    // Reconnect WiFi if disconnected
    // WiFi state tracking + auto-reconnect to any known network
    if (wifi_connected && WiFi.status() != WL_CONNECTED) {
        wifi_connected = false;
        face_set_wifi(false);
        Serial.println("[WIFI] Connection lost");
        last_wifi_retry = millis();  // retry soon
    }
    if (!wifi_connected) {
        unsigned long now = millis();
        if (now - last_wifi_retry >= WIFI_RETRY_MS) {
            last_wifi_retry = now;
            wifi_reconnect();
            if (wifi_connected) play_glitch_beep();
        }
    }

    // Update battery status periodically
    update_battery();

    // Check for due reminders (every 30s)
    check_reminders();

    // Drive face animations (non-blocking, ~20fps)
    face_update();

    // Check button press (LOW = pressed)
    if (digitalRead(BUTTON_PIN) == LOW) {
        delay(50);  // Debounce
        if (digitalRead(BUTTON_PIN) == LOW) {
            Serial.println("[GLITCH] Button pressed!");
            record_and_send();

            // Wait for button release
            while (digitalRead(BUTTON_PIN) == LOW) {
                delay(50);
            }
            delay(200);  // Debounce
        }
    }

    delay(10);  // Shorter delay for smoother animations
}
