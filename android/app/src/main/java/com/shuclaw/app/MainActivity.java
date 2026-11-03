package com.shuclaw.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;

/** Full-screen landscape WebView showing the controller page, plus native haptics and PC discovery. */
public class MainActivity extends Activity {
    private WebView web;
    private Haptics haptics;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        haptics = new Haptics(this);

        web = new WebView(this);
        web.setBackgroundColor(0xFF0E1016);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setHapticFeedbackEnabled(false);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // remembers settings and the last PC
        s.setTextZoom(100);             // ignore system font scaling so the layout stays put
        s.setSupportZoom(false);
        web.addJavascriptInterface(new Bridge(), "ShuclawNative");
        web.loadUrl("file:///android_asset/index.html");
        setContentView(web);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemBars();
    }

    @SuppressWarnings("deprecation")
    private void hideSystemBars() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.hide(WindowInsets.Type.systemBars());
                c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    @Override
    protected void onPause() {
        // let go of every button so nothing stays held in the game while the app is in the background
        web.evaluateJavascript("typeof releaseAll === 'function' && releaseAll()", null);
        haptics.stop();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        haptics.stop();
        web.destroy();
        super.onDestroy();
    }

    /** Called from the page's JavaScript (on a background thread). */
    private class Bridge {
        @JavascriptInterface
        public void haptic(String kind, int strength) {
            haptics.press(kind, strength);
        }

        @JavascriptInterface
        public void rumble(int large, int small) {
            haptics.rumble(large, small);
        }

        @JavascriptInterface
        public void discover() {
            new Thread(() -> {
                String json = Discovery.find(1500).toString();
                runOnUiThread(() -> web.evaluateJavascript("onPcsFound(" + json + ")", null));
            }).start();
        }
    }
}
