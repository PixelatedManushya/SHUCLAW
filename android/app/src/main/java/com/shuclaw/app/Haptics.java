package com.shuclaw.app;

import android.content.Context;
import android.media.AudioAttributes;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationAttributes;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;

/** Button-press clicks and game rumble on the phone's vibration motor. All work runs on the main thread. */
final class Haptics {
    private static final long RUMBLE_CHUNK_MS = 1000;   // re-issued while the game keeps rumbling
    private static final long MIN_RUMBLE_MS = 200;      // short or cancelled pulses are still felt

    private final Vibrator vib;
    private final Handler main = new Handler(Looper.getMainLooper());
    private int rumbleAmp = 0;        // 0-255, 0 = off
    private long rumbleStartedAt = 0;

    private final Runnable rumbleLoop = new Runnable() {
        @Override public void run() {
            if (rumbleAmp <= 0) return;
            int amp = vib.hasAmplitudeControl() ? rumbleAmp : VibrationEffect.DEFAULT_AMPLITUDE;
            vibrate(VibrationEffect.createOneShot(RUMBLE_CHUNK_MS, amp));
            main.postDelayed(this, RUMBLE_CHUNK_MS - 100);
        }
    };

    private final Runnable rumbleStop = new Runnable() {
        @Override public void run() {
            rumbleAmp = 0;
            main.removeCallbacks(rumbleLoop);
            vib.cancel();
        }
    };

    @SuppressWarnings("deprecation")
    Haptics(Context ctx) {
        if (Build.VERSION.SDK_INT >= 31) {
            vib = ((VibratorManager) ctx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE)).getDefaultVibrator();
        } else {
            vib = (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
        }
    }

    /**
     * Tags every vibration as media/game vibration. Untagged vibrations are silently blocked or
     * weakened on some phones; tagged ones follow the "Media vibration" setting.
     */
    @SuppressWarnings("deprecation")
    private void vibrate(VibrationEffect effect) {
        if (Build.VERSION.SDK_INT >= 33) {
            vib.vibrate(effect, VibrationAttributes.createForUsage(VibrationAttributes.USAGE_MEDIA));
        } else {
            vib.vibrate(effect, new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME).build());
        }
    }

    /** kind: "press", "tick" or "click"; strength: 1 light, 2 medium, 3 strong. */
    void press(String kind, int strength) {
        main.post(() -> {
            if (strength <= 0 || !vib.hasVibrator()) return;
            vibrate(effectFor(kind, strength));
            if (rumbleAmp > 0) {   // the click interrupted the rumble; pick it back up right after
                main.removeCallbacks(rumbleLoop);
                main.postDelayed(rumbleLoop, 50);
            }
        });
    }

    private VibrationEffect effectFor(String kind, int strength) {
        if (Build.VERSION.SDK_INT >= 29) {   // crisp, motor-tuned effects
            int id;
            if ("tick".equals(kind)) id = strength >= 3 ? VibrationEffect.EFFECT_CLICK : VibrationEffect.EFFECT_TICK;
            else if ("click".equals(kind)) id = VibrationEffect.EFFECT_DOUBLE_CLICK;
            else id = strength == 1 ? VibrationEffect.EFFECT_TICK
                    : strength == 2 ? VibrationEffect.EFFECT_CLICK : VibrationEffect.EFFECT_HEAVY_CLICK;
            return VibrationEffect.createPredefined(id);
        }
        long ms = "tick".equals(kind) ? 12 : 10 + strength * 8L;
        int amp = vib.hasAmplitudeControl() ? 70 + strength * 60 : VibrationEffect.DEFAULT_AMPLITUDE;
        return VibrationEffect.createOneShot(ms, amp);
    }

    /** Game motor values 0-255. The big motor is felt strongly, the small one more lightly. */
    void rumble(int large, int small) {
        main.post(() -> {
            int amp = Math.min(255, Math.max(large, small * 2 / 3));
            // phones without strength control would buzz at full power for faint rumble; skip those
            if (!vib.hasAmplitudeControl() && amp < 60) amp = 0;

            if (amp == 0) {
                if (rumbleAmp == 0) return;
                long left = MIN_RUMBLE_MS - (SystemClock.uptimeMillis() - rumbleStartedAt);
                main.removeCallbacks(rumbleStop);
                if (left > 0) main.postDelayed(rumbleStop, left); else rumbleStop.run();
                return;
            }
            main.removeCallbacks(rumbleStop);   // a new pulse cancels a pending stop
            if (amp == rumbleAmp) return;
            if (rumbleAmp == 0) rumbleStartedAt = SystemClock.uptimeMillis();
            rumbleAmp = amp;
            main.removeCallbacks(rumbleLoop);
            rumbleLoop.run();
        });
    }

    void stop() {
        main.post(() -> {
            main.removeCallbacks(rumbleStop);
            rumbleStop.run();
        });
    }
}
