/**
 * Minimal GFX Library header for Glitch ESP32.
 * Only includes QSPI databus + CO5300 display driver.
 * Based on moononournation/Arduino_GFX v1.6.4 (Waveshare fork).
 */
#ifndef _ARDUINO_GFX_LIBRARIES_H_
#define _ARDUINO_GFX_LIBRARIES_H_

#include "Arduino_DataBus.h"
#include "Arduino_GFX.h"
#include "Arduino_TFT.h"
#include "Arduino_OLED.h"

// Only the databus we need
#include "databus/Arduino_ESP32QSPI.h"

// Only the display we need
#include "display/Arduino_CO5300.h"

// Common color definitions
#define RGB565_BLACK   0x0000
#define RGB565_WHITE   0xFFFF
#define RGB565_RED     0xF800
#define RGB565_GREEN   0x07E0
#define RGB565_BLUE    0x001F
#define RGB565_CYAN    0x07FF
#define RGB565_YELLOW  0xFFE0

#endif // _ARDUINO_GFX_LIBRARIES_H_
