/**
 * ES8311 Speaker Codec Driver — Wire.h implementation
 *
 * Minimal driver for ES8311 DAC/speaker output using Arduino Wire.h
 * Compatible with PlatformIO + Arduino framework for ESP32-S3.
 *
 * Based on Waveshare SDK examples and Espressif ES8311 driver.
 */

#include <Arduino.h>
#include <Wire.h>
#include "es8311_reg.h"
#include "pin_config.h"

#define ES8311_ADDR   ((uint8_t)0x18)  // CE pin low
#define SPEAKER_TAG   "ES8311"

// ==================== I2C helpers ====================

static bool es8311_write_reg(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(ES8311_ADDR);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

static uint8_t es8311_read_reg(uint8_t reg) {
    Wire.beginTransmission(ES8311_ADDR);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom(ES8311_ADDR, (uint8_t)1);
    if (Wire.available()) {
        return Wire.read();
    }
    return 0;
}

// ==================== Clock coefficients ====================

struct coeff_div {
    uint32_t mclk;
    uint32_t rate;
    uint8_t pre_div;
    uint8_t pre_multi;
    uint8_t adc_div;
    uint8_t dac_div;
    uint8_t fs_mode;
    uint8_t lrck_h;
    uint8_t lrck_l;
    uint8_t bclk_div;
    uint8_t adc_osr;
    uint8_t dac_osr;
};

static const coeff_div coeffs[] = {
    // mclk       rate   pre_div mult  adc  dac  fs   lrch  lrcl  bck  aosr dosr
    {12288000, 16000, 0x03, 0x00, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {16384000, 16000, 0x04, 0x00, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    { 8192000, 16000, 0x02, 0x00, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    { 4096000, 16000, 0x01, 0x00, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    { 2048000, 16000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    { 1024000, 16000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
};

static int find_coeff(uint32_t mclk, uint32_t rate) {
    for (int i = 0; i < (int)(sizeof(coeffs) / sizeof(coeffs[0])); i++) {
        if (coeffs[i].rate == rate && coeffs[i].mclk == mclk) return i;
    }
    return -1;
}

// ==================== Public API ====================

/**
 * Initialize ES8311 codec for speaker output.
 * Call AFTER Wire.begin(SDA, SCL) and AFTER PA pin is set HIGH.
 *
 * @param sample_rate  Audio sample rate (e.g., 16000)
 * @param volume       Volume 0-100
 * @return true on success
 */
bool es8311_speaker_init(int sample_rate, int volume) {
    Serial.printf("[%s] Initializing speaker codec at %d Hz, vol=%d\n",
                  SPEAKER_TAG, sample_rate, volume);

    // Check if ES8311 is reachable
    Wire.beginTransmission(ES8311_ADDR);
    if (Wire.endTransmission() != 0) {
        Serial.printf("[%s] ERROR: ES8311 not found at 0x%02X\n", SPEAKER_TAG, ES8311_ADDR);
        return false;
    }

    // MCLK frequency = sample_rate * 256 (from MCLK pin)
    uint32_t mclk_freq = (uint32_t)sample_rate * 256;
    int ci = find_coeff(mclk_freq, sample_rate);

    // Reset codec
    es8311_write_reg(ES8311_RESET_REG00, 0x1F);
    delay(5);
    es8311_write_reg(ES8311_RESET_REG00, 0x00);
    delay(5);
    es8311_write_reg(ES8311_RESET_REG00, 0x80);  // Power on

    // Clock configuration
    es8311_write_reg(ES8311_CLK_MANAGER_REG01, 0x3F);  // Enable all clocks, MCLK from MCLK pin

    if (ci >= 0) {
        const coeff_div* c = &coeffs[ci];
        uint8_t reg02 = ((c->pre_div - 1) << 5) | (c->pre_multi << 3);
        es8311_write_reg(ES8311_CLK_MANAGER_REG02, reg02);
        es8311_write_reg(ES8311_CLK_MANAGER_REG03, (c->fs_mode << 6) | c->adc_osr);
        es8311_write_reg(ES8311_CLK_MANAGER_REG04, c->dac_osr);
        es8311_write_reg(ES8311_CLK_MANAGER_REG05, ((c->adc_div - 1) << 4) | (c->dac_div - 1));

        uint8_t reg06 = es8311_read_reg(ES8311_CLK_MANAGER_REG06);
        reg06 &= 0xE0;
        reg06 |= (c->bclk_div < 19) ? (c->bclk_div - 1) : c->bclk_div;
        es8311_write_reg(ES8311_CLK_MANAGER_REG06, reg06);

        uint8_t reg07 = es8311_read_reg(ES8311_CLK_MANAGER_REG07);
        reg07 &= 0xC0;
        reg07 |= c->lrck_h;
        es8311_write_reg(ES8311_CLK_MANAGER_REG07, reg07);
        es8311_write_reg(ES8311_CLK_MANAGER_REG08, c->lrck_l);
    } else {
        Serial.printf("[%s] WARNING: No clock coeff for mclk=%u rate=%d, using defaults\n",
                      SPEAKER_TAG, mclk_freq, sample_rate);
    }

    // SDP (Serial Data Port) — 16-bit I2S mode, slave
    uint8_t reg00 = es8311_read_reg(ES8311_RESET_REG00);
    reg00 &= 0xBF;  // Slave mode
    es8311_write_reg(ES8311_RESET_REG00, reg00);

    es8311_write_reg(ES8311_SDPIN_REG09,  0x0C);  // 16-bit input
    es8311_write_reg(ES8311_SDPOUT_REG0A, 0x0C);  // 16-bit output

    // Power up analog circuitry
    es8311_write_reg(ES8311_SYSTEM_REG0D, 0x01);
    es8311_write_reg(ES8311_SYSTEM_REG0E, 0x02);  // Enable analog PGA, ADC modulator
    es8311_write_reg(ES8311_SYSTEM_REG12, 0x00);  // Power up DAC
    es8311_write_reg(ES8311_SYSTEM_REG13, 0x10);  // Enable output to HP drive

    // ADC config (not strictly needed for speaker-only, but keeps codec happy)
    es8311_write_reg(ES8311_ADC_REG1C, 0x6A);  // ADC EQ bypass, cancel DC offset
    es8311_write_reg(ES8311_SYSTEM_REG14, 0x1A); // Enable analog MIC, max PGA gain

    // DAC config
    es8311_write_reg(ES8311_DAC_REG37, 0x08);  // Bypass DAC equalizer

    // Set volume (0-100 → 0-255)
    int reg32 = (volume == 0) ? 0 : ((volume * 256 / 100) - 1);
    es8311_write_reg(ES8311_DAC_REG32, (uint8_t)reg32);

    // Unmute DAC
    uint8_t reg31 = es8311_read_reg(ES8311_DAC_REG31);
    reg31 &= ~(0x60);  // Clear mute bits
    es8311_write_reg(ES8311_DAC_REG31, reg31);

    Serial.printf("[%s] Speaker codec initialized OK\n", SPEAKER_TAG);
    return true;
}

/**
 * Set speaker volume.
 * @param volume  0-100
 */
void es8311_set_volume(int volume) {
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    int reg32 = (volume == 0) ? 0 : ((volume * 256 / 100) - 1);
    es8311_write_reg(ES8311_DAC_REG32, (uint8_t)reg32);
}

/**
 * Mute or unmute the speaker.
 */
void es8311_mute(bool mute) {
    uint8_t reg31 = es8311_read_reg(ES8311_DAC_REG31);
    if (mute) {
        reg31 |= 0x60;
    } else {
        reg31 &= ~0x60;
    }
    es8311_write_reg(ES8311_DAC_REG31, reg31);
}
