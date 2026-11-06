package ai.chutku.phone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;

/**
 * The Chutku phone app: the account relay's phone page in a WebView. The relay address is asked once and kept; the
 * login (ID + password, made on the laptop) is kept by the page itself until the owner logs out.
 */
public class MainActivity extends Activity {
    private static final int MIC = 1, FILES = 2;
    private WebView web;
    private PermissionRequest waitingMic;
    private ValueCallback<Uri[]> waitingFiles;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        setContentView(web);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);                    // the device token stays in localStorage
        settings.setMediaPlaybackRequiresUserGesture(false);    // spoken replies and approvals play by themselves
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                Uri home = Uri.parse(relayUrl());
                if (target.getHost() != null && target.getHost().equals(home.getHost())) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, target));   // other sites open in the browser
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) askAddress("Could not reach " + relayUrl() + ". Check the address:");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                        request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                    } else {
                        waitingMic = request;
                        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MIC);
                    }
                });
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (waitingFiles != null) waitingFiles.onReceiveValue(null);
                waitingFiles = callback;
                startActivityForResult(params.createIntent(), FILES);
                return true;
            }
        });
        if (relayUrl().isEmpty()) askAddress("Your relay address (the same as CHUTKU_RELAY_URL on the laptop):");
        else web.loadUrl(relayUrl());
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("chutku", MODE_PRIVATE);
    }

    private String relayUrl() {
        return prefs().getString("relay", BuildConfig.RELAY_URL);
    }

    private void askAddress(String message) {
        EditText input = new EditText(this);
        input.setHint("https://relay.example.com");
        input.setText(relayUrl());
        new AlertDialog.Builder(this).setTitle("Chutku").setMessage(message).setView(input).setCancelable(false)
                .setPositiveButton("Connect", (dialog, which) -> {
                    String url = input.getText().toString().trim().replaceAll("/+$", "");
                    if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://" + url;
                    prefs().edit().putString("relay", url).apply();
                    web.loadUrl(url);
                }).show();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        if (code == MIC && waitingMic != null) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
                waitingMic.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            } else {
                waitingMic.deny();
            }
            waitingMic = null;
        }
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        if (code == FILES && waitingFiles != null) {
            waitingFiles.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            waitingFiles = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
