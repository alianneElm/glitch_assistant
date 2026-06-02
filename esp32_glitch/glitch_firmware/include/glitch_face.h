/**
 * Glitch Face — Animated face display for AMOLED
 *
 * Shows a cyberpunk face image with animated overlays per state.
 * The base face is a 466x466 RGB565 bitmap stored in PROGMEM.
 * Animated overlays are drawn on top for different states.
 */

#pragma once
#include <Arduino.h>
#include "Arduino_GFX_Library.h"

// Face states
enum GlitchState {
    STATE_BOOT,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_THINKING,
    STATE_SPEAKING,
    STATE_ERROR,
    STATE_RESPONSE,
};

// Initialize face system (copies face data to PSRAM framebuffer)
void face_init(Arduino_GFX* gfx);

// Set current state (triggers overlay change)
void face_set_state(GlitchState state);

// Draw current frame — call this in loop() for animations
// Returns true if display was updated
bool face_update();

// Show response text on screen (overlaid on face)
void face_show_response(const char* transcript, const char* reply);

// Set WiFi status indicator
void face_set_wifi(bool connected);

// Battery info struct
struct BatteryInfo {
    int percent;        // 0-100, or -1 if no battery
    int voltage_mv;     // millivolts
    bool charging;      // actively charging
    bool usb_in;        // USB-C plugged in
    uint8_t charge_state; // 0=tri,1=pre,2=CC,3=CV,4=done,5=stopped
};

// Set battery status — call periodically from main loop
void face_set_battery(const BatteryInfo& info);
