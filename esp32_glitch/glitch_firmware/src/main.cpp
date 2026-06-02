/**
 * Glitch ESP32 Firmware — Phase 4
 *
 * Waveshare ESP32-S3-Touch-AMOLED-1.75C
 * Press button → record audio → send to Glitch backend → play beep → show response
 *
 * Hardware:
 *   - ES7210: 4-channel ADC (microphone input)
 *   - ES8311: DAC (speaker output)
 *   - PA (GPIO 46): Power amplifier enable
 *   - I2S bus shared: BCK=9, WS=45, MCLK=16, DIN=10, DOUT=8
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include "pin_config.h"
#include "es7210.h"
#include "audio_hal.h"
#include "es8311_speaker.h"

// ==================== CONFIG ====================
const char* WIFI_SSID     = "TP_LINK_D9F7";
const char* WIFI_PASSWORD = "42209317";
const char* GLITCH_URL    = "https://alluring-courtesy-production-9b65.up.railway.app";
const char* USER_ID       = "+46762547179";

// Audio settings
#define SAMPLE_RATE     16000
#define RECORD_SECONDS  5
#define I2S_CH          I2S_NUM_1
#define BUFFER_SIZE     1024
#define SPEAKER_VOLUME  85

// Button
#define BUTTON_PIN      0  // Small button (BOOT)

// ==================== GLOBALS ====================
bool recording = false;
bool wifi_connected = false;
bool speaker_ready = false;

// ==================== WIFI ====================
void setup_wifi() {
    Serial.printf("[GLITCH] Connecting to WiFi: %s\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int timeout = 0;
    while (WiFi.status() != WL_CONNECTED && timeout < 20) {
        delay(500);
        Serial.print(".");
        timeout++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        wifi_connected = true;
        Serial.printf("\n[GLITCH] WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\n[GLITCH] WiFi timeout — continuing without network");
        Serial.println("[GLITCH] Make sure your router uses 2.4 GHz (ESP32 doesn't support 5 GHz)");
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
    // I2S config for speaker output (ES8311)
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
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
        (es7210_gain_value_t)GAIN_0DB
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
            // Sine wave with soft envelope (fade in/out)
            float env = 1.0f;
            int fade_samples = SAMPLE_RATE / 20;  // 50ms fade
            if (samples_written + i < fade_samples) {
                env = (float)(samples_written + i) / fade_samples;
            } else if (total_samples - (samples_written + i) < fade_samples) {
                env = (float)(total_samples - (samples_written + i)) / fade_samples;
            }
            buf[i] = (int16_t)(sinf(phase) * 16000.0f * env);
            phase += phase_inc;
            if (phase >= 2.0f * PI) phase -= 2.0f * PI;
        }
        i2s_write(I2S_CH, (char*)buf, to_write * sizeof(int16_t), &bytes_written, portMAX_DELAY);
        samples_written += to_write;
    }

    // Flush with silence
    memset(buf, 0, chunk_size * sizeof(int16_t));
    i2s_write(I2S_CH, (char*)buf, chunk_size * sizeof(int16_t), &bytes_written, portMAX_DELAY);

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
                int fade = SAMPLE_RATE / 50;  // 20ms fade
                if (samples_written + i < fade)
                    env = (float)(samples_written + i) / fade;
                else if (total_samples - (samples_written + i) < fade)
                    env = (float)(total_samples - (samples_written + i)) / fade;
                buf[i] = (int16_t)(sinf(phase) * 14000.0f * env);
                phase += phase_inc;
                if (phase >= 2.0f * PI) phase -= 2.0f * PI;
            }
            i2s_write(I2S_CH, (char*)buf, to_write * sizeof(int16_t), &bytes_written, portMAX_DELAY);
            samples_written += to_write;
        }

        // Small gap between tones
        if (t == 0) {
            memset(buf, 0, chunk_size * sizeof(int16_t));
            i2s_write(I2S_CH, (char*)buf, chunk_size * sizeof(int16_t), &bytes_written, portMAX_DELAY);
        }
    }

    // Flush silence
    memset(buf, 0, chunk_size * sizeof(int16_t));
    i2s_write(I2S_CH, (char*)buf, chunk_size * sizeof(int16_t), &bytes_written, portMAX_DELAY);

    free(buf);

    // Back to RX
    i2s_driver_uninstall(I2S_CH);
    i2s_install_rx();
}

// ==================== RECORD + SEND ====================
void record_and_send() {
    if (!wifi_connected) {
        Serial.println("[GLITCH] No WiFi — cannot send audio");
        play_beep(200, 500);  // Low error tone
        return;
    }

    // Recording start beep
    play_beep(660, 100);

    Serial.println("[GLITCH] Recording...");
    recording = true;

    // Allocate buffer in PSRAM for audio data
    int total_samples = SAMPLE_RATE * RECORD_SECONDS;
    int total_bytes = total_samples * sizeof(int16_t);
    int16_t* audio_buffer = (int16_t*)ps_malloc(total_bytes);

    if (!audio_buffer) {
        Serial.println("[GLITCH] Failed to allocate audio buffer!");
        recording = false;
        return;
    }

    // Record audio
    int offset = 0;
    size_t bytes_read;
    unsigned long start_time = millis();

    while (offset < total_samples && (millis() - start_time) < (RECORD_SECONDS * 1000 + 500)) {
        int to_read = min(BUFFER_SIZE, total_samples - offset);
        i2s_read(I2S_CH, (char*)(audio_buffer + offset), to_read * sizeof(int16_t), &bytes_read, portMAX_DELAY);
        offset += bytes_read / sizeof(int16_t);
    }

    Serial.printf("[GLITCH] Recorded %d samples (%d bytes)\n", offset, offset * 2);
    recording = false;

    // Recording end beep
    play_beep(880, 100);

    // Send to backend
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

            Serial.println("=== GLITCH RESPONSE ===");
            Serial.printf("  Status:     %s\n", status);
            Serial.printf("  You said:   %s\n", transcript);
            Serial.printf("  Glitch:     %s\n", reply);
            if (strlen(audio_url) > 0) {
                Serial.printf("  Audio URL:  %s\n", audio_url);
            }
            Serial.println("=======================");

            // Success feedback
            if (strcmp(status, "success") == 0) {
                play_glitch_beep();  // Happy chirp
            } else {
                play_beep(330, 300);  // Error tone
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
        play_beep(220, 500);  // Low error tone
    }

    http.end();
    free(audio_buffer);

    Serial.println("[GLITCH] Ready for next command");
}

// ==================== SETUP ====================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("========================================");
    Serial.println("  Glitch ESP32 — Phase 4");
    Serial.println("  Waveshare ESP32-S3-AMOLED-1.75C");
    Serial.println("========================================");
    Serial.printf("PSRAM: %d KB\n", ESP.getPsramSize() / 1024);
    Serial.printf("Flash: %d KB\n", ESP.getFlashChipSize() / 1024);

    // Button setup
    pinMode(BUTTON_PIN, INPUT);

    // Power amplifier enable
    pinMode(PA, OUTPUT);
    digitalWrite(PA, HIGH);

    // I2C bus (shared by ES7210 + ES8311)
    Wire.begin(IIC_SDA, IIC_SCL);
    delay(200);

    // Connect WiFi
    setup_wifi();

    // Initialize audio codecs
    setup_microphone();
    setup_speaker();

    // Boot chime
    play_glitch_beep();

    Serial.println("\n[GLITCH] Ready! Press button to talk.");
}

// ==================== LOOP ====================
void loop() {
    // Reconnect WiFi if disconnected
    if (!wifi_connected && WiFi.status() == WL_CONNECTED) {
        wifi_connected = true;
        Serial.println("[GLITCH] WiFi reconnected!");
        play_glitch_beep();
    } else if (wifi_connected && WiFi.status() != WL_CONNECTED) {
        wifi_connected = false;
        Serial.println("[GLITCH] WiFi lost!");
    }

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

    delay(50);
}
