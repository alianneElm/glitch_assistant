/**
 * Glitch Face — Static face with bottom HUD panel
 *
 * Face image drawn ONCE per state change. No animation loop.
 * Bottom area: status label + battery info panel.
 * Right side: WiFi indicator.
 */

#include "glitch_face.h"
#include "glitch_face_data.h"
#include "pin_config.h"
#include <math.h>

// ==================== GLOBALS ====================
static Arduino_GFX* _gfx = nullptr;
static GlitchState _state = STATE_BOOT;
static GlitchState _prev_state = STATE_BOOT;
static bool _wifi = false;

// Battery state
static BatteryInfo _batt = { -1, 0, false, false, 5 };
static BatteryInfo _prev_batt = { -2, 0, false, false, 5 };

// PSRAM copy of face data
static uint16_t* _face_psram = nullptr;

// Colors (RGB565)
#define CLR_CYAN     0x07FF
#define CLR_MAGENTA  0xF81F
#define CLR_GREEN    0x07E0
#define CLR_RED      0xF800
#define CLR_ORANGE   0xFD20
#define CLR_WHITE    0xFFFF
#define CLR_DIM      0x7BEF  // lighter gray for readability
#define CLR_DARK     0x18E3
#define CLR_BLACK    0x0000

// HUD panel geometry — bottom of screen
#define HUD_Y        (LCD_HEIGHT - 80)  // top of HUD area
#define HUD_H        80                  // height of HUD area

// ==================== INTERNAL HELPERS ====================

static void _draw_face() {
    if (_face_psram) {
        _gfx->draw16bitRGBBitmap(0, 0, _face_psram, GLITCH_FACE_WIDTH, GLITCH_FACE_HEIGHT);
    } else {
        _gfx->draw16bitRGBBitmap(0, 0, glitch_face_data, GLITCH_FACE_WIDTH, GLITCH_FACE_HEIGHT);
    }
}

// Restore a region from the face bitmap
static void _restore_region(int x, int y, int w, int h) {
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > LCD_WIDTH) w = LCD_WIDTH - x;
    if (y + h > LCD_HEIGHT) h = LCD_HEIGHT - y;
    if (w <= 0 || h <= 0) return;
    uint16_t* src = _face_psram ? _face_psram : (uint16_t*)glitch_face_data;
    for (int row = 0; row < h; row++) {
        int off = (y + row) * GLITCH_FACE_WIDTH + x;
        _gfx->draw16bitRGBBitmap(x, y + row, src + off, w, 1);
    }
}

// ==================== BOTTOM HUD PANEL ====================

// Draw solid dark panel at bottom
static void _draw_hud_bg() {
    _gfx->fillRect(0, HUD_Y, LCD_WIDTH, HUD_H, CLR_BLACK);
    // Top border line
    _gfx->drawFastHLine(20, HUD_Y, LCD_WIDTH - 40, CLR_CYAN);
}

// Draw text with full black outline (8 directions) for maximum readability
static void _draw_text_outlined(int x, int y, const char* text, uint16_t color, uint8_t size) {
    _gfx->setTextSize(size);
    _gfx->setTextColor(CLR_BLACK);
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (dx == 0 && dy == 0) continue;
            _gfx->setCursor(x + dx, y + dy);
            _gfx->print(text);
        }
    }
    _gfx->setTextColor(color);
    _gfx->setCursor(x, y);
    _gfx->print(text);
}

// Get charge state label
static const char* _charge_state_label(uint8_t state) {
    switch (state) {
        case 0: return "Trickle";
        case 1: return "Pre-charge";
        case 2: return "CC charge";
        case 3: return "CV charge";
        case 4: return "Done";
        case 5: return "Idle";
        default: return "Unknown";
    }
}

// Draw the full HUD: status label + battery info
static void _draw_hud(const char* status_text, uint16_t status_color) {
    _draw_hud_bg();

    int cx = LCD_WIDTH / 2;
    int16_t x1, y1;
    uint16_t tw, th;

    // ---- ROW 1: Status label ----
    int row1_y = HUD_Y + 8;
    _gfx->setTextSize(2);
    _gfx->getTextBounds(status_text, 0, 0, &x1, &y1, &tw, &th);
    _draw_text_outlined(cx - tw / 2, row1_y, status_text, status_color, 2);

    // ---- ROW 2: Battery percentage ----
    int row2_y = row1_y + 22;

    if (_batt.percent >= 0) {
        uint16_t batt_color;
        if (_batt.percent > 60)      batt_color = CLR_GREEN;
        else if (_batt.percent > 20) batt_color = CLR_ORANGE;
        else                         batt_color = CLR_RED;

        // Charging bolt ⚡ to the left of the percentage
        if (_batt.charging) {
            int bx = cx - 52;
            int by = row2_y + 1;
            _gfx->drawLine(bx + 5, by,      bx + 1, by + 7,  CLR_CYAN);
            _gfx->drawLine(bx + 1, by + 7,  bx + 6, by + 7,  CLR_CYAN);
            _gfx->drawLine(bx + 6, by + 7,  bx + 2, by + 14, CLR_CYAN);
        }

        char pct[8];
        snprintf(pct, sizeof(pct), "%d%%", _batt.percent);
        _gfx->setTextSize(2);
        _gfx->getTextBounds(pct, 0, 0, &x1, &y1, &tw, &th);
        _draw_text_outlined(cx - tw / 2, row2_y, pct, batt_color, 2);

        // ---- ROW 3: Charge state label ----
        int row3_y = row2_y + 20;
        // Row 3: voltage + charge state label
        char row3_str[32];
        float volts = _batt.voltage_mv / 1000.0f;
        if (_batt.charging) {
            snprintf(row3_str, sizeof(row3_str), "%.2fV  %s",
                     volts, _charge_state_label(_batt.charge_state));
        } else if (_batt.usb_in) {
            snprintf(row3_str, sizeof(row3_str), "%.2fV  Charge complete", volts);
        } else {
            snprintf(row3_str, sizeof(row3_str), "%.2fV  On battery", volts);
        }
        _gfx->setTextSize(1);
        _gfx->getTextBounds(row3_str, 0, 0, &x1, &y1, &tw, &th);
        _draw_text_outlined(cx - tw / 2, row3_y, row3_str, CLR_DIM, 1);

    } else {
        // No battery info
        const char* usb_text = _batt.usb_in ? "USB-C connected" : "No battery";
        uint16_t usb_color   = _batt.usb_in ? CLR_CYAN : CLR_DIM;
        _gfx->setTextSize(1);
        _gfx->getTextBounds(usb_text, 0, 0, &x1, &y1, &tw, &th);
        _draw_text_outlined(cx - tw / 2, row2_y + 4, usb_text, usb_color, 1);
    }
}

// ==================== WIFI INDICATOR (right side, near HUD) ====================

static void _draw_wifi() {
    int x = LCD_WIDTH - 45;
    int y = HUD_Y + 10;

    uint16_t color = _wifi ? CLR_GREEN : CLR_RED;

    if (_wifi) {
        _gfx->fillCircle(x, y + 16, 2, color);
        _gfx->drawArc(x, y + 16, 6, 8, 225, 315, color);
        _gfx->drawArc(x, y + 16, 12, 14, 225, 315, color);
    } else {
        _gfx->drawLine(x - 6, y + 8, x + 6, y + 20, CLR_RED);
        _gfx->drawLine(x + 6, y + 8, x - 6, y + 20, CLR_RED);
    }
}

// ==================== PUBLIC API ====================

void face_init(Arduino_GFX* gfx) {
    _gfx = gfx;
    _state = STATE_BOOT;

    size_t face_bytes = GLITCH_FACE_WIDTH * GLITCH_FACE_HEIGHT * sizeof(uint16_t);
    Serial.printf("[FACE] Allocating %d KB PSRAM for face buffer...\n", face_bytes / 1024);

    _face_psram = (uint16_t*)ps_malloc(face_bytes);
    if (_face_psram) {
        memcpy(_face_psram, glitch_face_data, face_bytes);
        Serial.println("[FACE] Face data copied to PSRAM");
    } else {
        Serial.println("[FACE] PSRAM alloc failed — using flash directly");
    }

    unsigned long t0 = millis();
    _draw_face();
    Serial.printf("[FACE] Face drawn in %lu ms\n", millis() - t0);
}

void face_set_state(GlitchState state) {
    if (state == _state) return;
    _prev_state = _state;
    _state = state;
    Serial.printf("[FACE] State: %d → %d\n", _prev_state, _state);

    if (!_gfx) return;

    // Redraw face (clears old overlays)
    _draw_face();

    const char* label = "READY";
    uint16_t color = CLR_CYAN;

    switch (_state) {
        case STATE_BOOT:      label = "BOOTING...";   color = CLR_CYAN;    break;
        case STATE_IDLE:      label = "READY";         color = CLR_CYAN;    break;
        case STATE_LISTENING: label = "LISTENING...";  color = CLR_GREEN;   break;
        case STATE_THINKING:  label = "THINKING...";   color = CLR_MAGENTA; break;
        case STATE_SPEAKING:  label = "SPEAKING...";   color = CLR_CYAN;    break;
        case STATE_ERROR:     label = "ERROR";         color = CLR_RED;     break;
        case STATE_RESPONSE:
            // Response has its own overlay — skip HUD
            return;
        default: break;
    }

    _draw_hud(label, color);
    _draw_wifi();
}

void face_set_wifi(bool connected) {
    if (_wifi == connected) return;
    _wifi = connected;
    if (_gfx && _state != STATE_RESPONSE) {
        _draw_wifi();
    }
}

void face_set_battery(const BatteryInfo& info) {
    bool changed = (info.percent != _prev_batt.percent) ||
                   (info.charging != _prev_batt.charging) ||
                   (info.usb_in != _prev_batt.usb_in) ||
                   (info.charge_state != _prev_batt.charge_state);

    _batt = info;

    if (changed && _gfx && _state != STATE_RESPONSE) {
        // Redraw the full HUD (status + battery) to keep it consistent
        const char* label = "READY";
        uint16_t color = CLR_CYAN;
        switch (_state) {
            case STATE_BOOT:      label = "BOOTING...";   color = CLR_CYAN;    break;
            case STATE_IDLE:      label = "READY";         color = CLR_CYAN;    break;
            case STATE_LISTENING: label = "LISTENING...";  color = CLR_GREEN;   break;
            case STATE_THINKING:  label = "THINKING...";   color = CLR_MAGENTA; break;
            case STATE_SPEAKING:  label = "SPEAKING...";   color = CLR_CYAN;    break;
            case STATE_ERROR:     label = "ERROR";         color = CLR_RED;     break;
            default: break;
        }

        // Restore face in HUD area, then redraw HUD
        _restore_region(0, HUD_Y - 2, LCD_WIDTH, HUD_H + 4);
        _draw_hud(label, color);
        _draw_wifi();

        _prev_batt = info;
    }
}

bool face_update() {
    // Event-driven — no animation needed
    return false;
}

void face_show_response(const char* transcript, const char* reply) {
    if (!_gfx) return;
    _state = STATE_RESPONSE;

    _draw_face();

    // Dark gradient overlay on bottom 60%
    int overlay_start = LCD_HEIGHT * 2 / 5;
    for (int y = overlay_start; y < LCD_HEIGHT; y++) {
        float t = (float)(y - overlay_start) / (LCD_HEIGHT - overlay_start);
        if (t > 0.25f || (y % 3 == 0)) {
            _gfx->drawFastHLine(0, y, LCD_WIDTH, CLR_BLACK);
        }
    }

    // "Tu:" label
    _draw_text_outlined(30, overlay_start + 15, "Tu:", CLR_DIM, 2);

    // Transcript
    _gfx->setTextWrap(true);
    char trunc[80];
    strncpy(trunc, transcript, sizeof(trunc) - 1);
    trunc[sizeof(trunc) - 1] = '\0';
    _draw_text_outlined(30, overlay_start + 40, trunc, CLR_WHITE, 2);

    // Divider
    int div_y = LCD_HEIGHT / 2 + 15;
    _gfx->drawFastHLine(30, div_y, LCD_WIDTH - 60, CLR_CYAN);

    // "Glitch:" label
    _draw_text_outlined(30, div_y + 12, "Glitch:", CLR_CYAN, 2);

    // Reply
    char reply_trunc[160];
    strncpy(reply_trunc, reply, sizeof(reply_trunc) - 1);
    reply_trunc[sizeof(reply_trunc) - 1] = '\0';
    _gfx->setTextWrap(true);
    _draw_text_outlined(30, div_y + 38, reply_trunc, CLR_WHITE, 2);
}
