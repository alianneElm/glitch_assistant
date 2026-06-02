#pragma once

/**
 * Initialize ES8311 codec for speaker output.
 * Must call Wire.begin() and set PA pin HIGH before calling this.
 *
 * @param sample_rate  Audio sample rate (e.g., 16000)
 * @param volume       Volume 0-100
 * @return true on success
 */
bool es8311_speaker_init(int sample_rate, int volume);

/**
 * Set speaker volume (0-100).
 */
void es8311_set_volume(int volume);

/**
 * Mute or unmute the speaker.
 */
void es8311_mute(bool mute);
