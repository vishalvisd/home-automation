package com.visd.ha;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.util.Locale;
import java.util.regex.Pattern;

/**
 * The whole app: one screen that shows the web page the Pi serves,
 * opened on the Live View tab.
 *
 * Besides the page there is one more screen, the Pi address. It appears
 * by itself when the Pi does not answer, and from "Pi address" in the
 * menu that opens when the app icon is pressed and held.
 */
public class MainActivity extends Activity {

    /** Sent by the "Pi address" entry of the app icon's menu. */
    private static final String ACTION_SHOW_ADDRESS = "com.visd.ha.SHOW_ADDRESS";

    /** The Pi's address when the app is first installed. */
    private static final String DEFAULT_ADDRESS = "192.168.1.31:8000";

    /** Used when an address is typed without a port. */
    private static final String DEFAULT_PORT = "8000";

    /** The page honours "?tab=live" and starts on Live View. */
    private static final String START_PATH = "/?tab=live";

    /** How long to wait for the Pi before saying it cannot be reached. */
    private static final long OPEN_TIMEOUT_MS = 10_000;

    /**
     * After this long in the background the page is loaded afresh on
     * return, so a page from before a Pi update is not kept for days.
     */
    private static final long RELOAD_AFTER_MS = 10 * 60 * 1000;

    private static final String SETTINGS_FILE = "settings";
    private static final String SETTING_ADDRESS = "pi_address";

    /** A host name or IP address, with or without a port. */
    private static final Pattern ADDRESS_PATTERN =
            Pattern.compile("[A-Za-z0-9.\\-]+(:[0-9]{1,5})?");

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable openTimeout = this::onOpenTimeout;

    private WebView webView;
    private View statusView;
    private View addressPanel;
    private TextView addressMessage;
    private EditText addressInput;
    private FrameLayout fullscreenHolder;

    /** True once the Pi's page is on the screen. */
    private boolean pageShown;

    /** True when the page being loaded has already failed. */
    private boolean loadFailed;

    /** When the app went to the background, or 0 when it did not. */
    private long stoppedAt;

    /** A video the page has put in full screen, with its way back. */
    private View fullscreenView;
    private WebChromeClient.CustomViewCallback fullscreenCallback;
    private int systemUiBeforeFullscreen;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);

        webView = findViewById(R.id.web);
        statusView = findViewById(R.id.status);
        addressPanel = findViewById(R.id.address_panel);
        addressMessage = findViewById(R.id.address_message);
        addressInput = findViewById(R.id.address_input);
        fullscreenHolder = findViewById(R.id.fullscreen);

        setUpWebView();
        setUpAddressPanel();

        if (ACTION_SHOW_ADDRESS.equals(getIntent().getAction())) {
            showAddressPanel(getString(R.string.address_intro));
        } else {
            loadPage();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);

        if (ACTION_SHOW_ADDRESS.equals(intent.getAction())) {
            showAddressPanel(getString(R.string.address_intro));
        }
    }

    // ------------------------------------------------------------------
    // The web page
    // ------------------------------------------------------------------

    private void setUpWebView() {
        WebSettings settings = webView.getSettings();

        // The page is a JavaScript application.
        settings.setJavaScriptEnabled(true);
        // The page remembers the ticked cameras and Main/Sub here.
        settings.setDomStorageEnabled(true);
        // Let the cameras start playing without a tap on each one.
        settings.setMediaPlaybackRequiresUserGesture(false);
        // The page never needs files or other apps' data on the phone.
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        // Do not send the addresses the app opens to Google for checking.
        settings.setSafeBrowsingEnabled(false);

        webView.setWebViewClient(new PageClient());
        webView.setWebChromeClient(new FullscreenClient());

        // The app keeps no files. A download is handed to the browser.
        webView.setDownloadListener(
                (url, userAgent, disposition, mimeType, length) ->
                        openOutside(Uri.parse(url)));
    }

    /** Loads the Pi's page from the saved address. */
    private void loadPage() {
        hideKeyboard();
        addressPanel.setVisibility(View.GONE);
        statusView.setVisibility(View.VISIBLE);

        pageShown = false;
        loadFailed = false;

        handler.removeCallbacks(openTimeout);
        handler.postDelayed(openTimeout, OPEN_TIMEOUT_MS);

        webView.loadUrl("http://" + savedAddress() + START_PATH);
    }

    /** The page has arrived: take the "Opening" text away. */
    private void onPageArrived() {
        if (loadFailed) {
            return;
        }

        handler.removeCallbacks(openTimeout);
        pageShown = true;
        statusView.setVisibility(View.GONE);
    }

    /** The Pi did not answer, or answered with an error. */
    private void onPageFailed() {
        handler.removeCallbacks(openTimeout);
        loadFailed = true;
        pageShown = false;

        showAddressPanel(
                getString(R.string.address_unreachable, savedAddress()));
    }

    private void onOpenTimeout() {
        if (pageShown || loadFailed) {
            return;
        }

        webView.stopLoading();
        onPageFailed();
    }

    private class PageClient extends WebViewClient {

        @Override
        public void onPageCommitVisible(WebView view, String url) {
            onPageArrived();
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            onPageArrived();
        }

        @Override
        public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error) {
            // Only the page itself counts. A camera that does not
            // connect is shown by the page, as in a browser.
            if (request.isForMainFrame()) {
                onPageFailed();
            }
        }

        @Override
        public void onReceivedHttpError(
                WebView view,
                WebResourceRequest request,
                WebResourceResponse response) {
            if (request.isForMainFrame()) {
                onPageFailed();
            }
        }

        @Override
        public boolean shouldOverrideUrlLoading(
                WebView view,
                WebResourceRequest request) {
            Uri target = request.getUrl();

            // Stay inside the app for anything on the Pi.
            if (hostOf(savedAddress()).equalsIgnoreCase(target.getHost())) {
                return false;
            }

            // Anything else belongs in the phone's browser.
            openOutside(target);
            return true;
        }
    }

    private void openOutside(Uri target) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, target));
        } catch (ActivityNotFoundException | SecurityException ignored) {
            // No app on the phone can open it. Nothing to do.
        }
    }

    // ------------------------------------------------------------------
    // Full-screen video
    // ------------------------------------------------------------------

    /**
     * A video player's full-screen button does nothing in a web view
     * unless the app provides the full screen. This does.
     */
    private class FullscreenClient extends WebChromeClient {

        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            if (fullscreenView != null) {
                callback.onCustomViewHidden();
                return;
            }

            fullscreenView = view;
            fullscreenCallback = callback;

            fullscreenHolder.addView(
                    view,
                    new FrameLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT));
            fullscreenHolder.setVisibility(View.VISIBLE);
            hideSystemBars(true);
        }

        @Override
        public void onHideCustomView() {
            leaveFullscreen();
        }
    }

    private void leaveFullscreen() {
        if (fullscreenView == null) {
            return;
        }

        hideSystemBars(false);
        fullscreenHolder.removeView(fullscreenView);
        fullscreenHolder.setVisibility(View.GONE);
        fullscreenView = null;

        WebChromeClient.CustomViewCallback callback = fullscreenCallback;
        fullscreenCallback = null;

        if (callback != null) {
            callback.onCustomViewHidden();
        }
    }

    @SuppressWarnings("deprecation")
    private void hideSystemBars(boolean hide) {
        View decor = getWindow().getDecorView();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = decor.getWindowInsetsController();

            if (controller == null) {
                return;
            }

            if (hide) {
                controller.setSystemBarsBehavior(
                        WindowInsetsController
                                .BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                controller.hide(WindowInsets.Type.systemBars());
            } else {
                controller.show(WindowInsets.Type.systemBars());
            }

            return;
        }

        // Android 8 to 10.
        if (hide) {
            systemUiBeforeFullscreen = decor.getSystemUiVisibility();
            decor.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        } else {
            decor.setSystemUiVisibility(systemUiBeforeFullscreen);
        }
    }

    // ------------------------------------------------------------------
    // The Pi address screen
    // ------------------------------------------------------------------

    private void setUpAddressPanel() {
        Button open = findViewById(R.id.address_open);
        open.setOnClickListener(view -> saveAddressAndOpen());

        addressInput.setOnEditorActionListener((view, action, event) -> {
            if (action == EditorInfo.IME_ACTION_GO) {
                saveAddressAndOpen();
                return true;
            }

            return false;
        });
    }

    private void showAddressPanel(String message) {
        leaveFullscreen();
        handler.removeCallbacks(openTimeout);

        addressMessage.setText(message);
        addressInput.setText(savedAddress());
        addressInput.setError(null);
        addressPanel.setVisibility(View.VISIBLE);
    }

    private void saveAddressAndOpen() {
        String address = tidyAddress(addressInput.getText().toString());

        if (address == null) {
            addressInput.setError(getString(R.string.address_invalid));
            return;
        }

        settings().edit().putString(SETTING_ADDRESS, address).apply();
        loadPage();
    }

    /**
     * Turns what was typed into "host:port", or null when it is not an
     * address. "http://" in front and anything after a "/" are dropped.
     * The Pi serves plain HTTP only, so the app always uses http.
     */
    static String tidyAddress(String typed) {
        String address = typed.trim();
        String lower = address.toLowerCase(Locale.ROOT);

        if (lower.startsWith("http://")) {
            address = address.substring("http://".length());
        } else if (lower.startsWith("https://")) {
            address = address.substring("https://".length());
        }

        int slash = address.indexOf('/');

        if (slash >= 0) {
            address = address.substring(0, slash);
        }

        if (!ADDRESS_PATTERN.matcher(address).matches()) {
            return null;
        }

        if (!address.contains(":")) {
            address = address + ":" + DEFAULT_PORT;
        }

        return address;
    }

    static String hostOf(String address) {
        int colon = address.indexOf(':');

        return colon >= 0 ? address.substring(0, colon) : address;
    }

    private SharedPreferences settings() {
        return getSharedPreferences(SETTINGS_FILE, Context.MODE_PRIVATE);
    }

    private String savedAddress() {
        return settings().getString(SETTING_ADDRESS, DEFAULT_ADDRESS);
    }

    private void hideKeyboard() {
        InputMethodManager keyboard =
                (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);

        if (keyboard != null) {
            keyboard.hideSoftInputFromWindow(addressInput.getWindowToken(), 0);
        }
    }

    // ------------------------------------------------------------------
    // Back button, background and foreground
    // ------------------------------------------------------------------

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (fullscreenView != null) {
            leaveFullscreen();
            return;
        }

        // The address screen opened over a working page: back to the page.
        if (addressPanel.getVisibility() == View.VISIBLE && pageShown) {
            hideKeyboard();
            addressPanel.setVisibility(View.GONE);
            return;
        }

        if (addressPanel.getVisibility() != View.VISIBLE
                && webView.canGoBack()) {
            webView.goBack();
            return;
        }

        super.onBackPressed();
    }

    @Override
    protected void onStart() {
        super.onStart();
        webView.onResume();

        boolean awayLong = stoppedAt != 0
                && SystemClock.elapsedRealtime() - stoppedAt > RELOAD_AFTER_MS;
        stoppedAt = 0;

        if (awayLong && addressPanel.getVisibility() != View.VISIBLE) {
            loadPage();
        }
    }

    @Override
    protected void onStop() {
        // Tells the page it is hidden. The player then closes its camera
        // connections, so nothing streams while the app is not on screen.
        webView.onPause();
        stoppedAt = SystemClock.elapsedRealtime();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(openTimeout);
        leaveFullscreen();

        ViewGroup parent = (ViewGroup) webView.getParent();

        if (parent != null) {
            parent.removeView(webView);
        }

        webView.destroy();
        super.onDestroy();
    }
}
