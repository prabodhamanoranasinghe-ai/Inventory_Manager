package com.inventory.mobile

import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.print.PrintAttributes
import android.print.PrintManager
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import androidx.core.net.toUri
import com.google.android.material.appbar.MaterialToolbar

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var topBar: MaterialToolbar

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        topBar = findViewById(R.id.topBar)
        webView = findViewById(R.id.inventoryWebView)
        setSupportActionBar(topBar)

        configureWebView()
        configureQuickActions()
        configureBackHandler()

        if (savedInstanceState == null) {
            loadRoute("/auth/login")
        } else {
            webView.restoreState(savedInstanceState)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        webView.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    override fun onCreateOptionsMenu(menu: android.view.Menu): Boolean {
        menuInflater.inflate(R.menu.main_actions, menu)
        return true
    }

    override fun onOptionsItemSelected(item: android.view.MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_refresh -> {
                webView.reload()
                true
            }
            R.id.action_open_settings -> {
                startActivity(Intent(this, SettingsActivity::class.java))
                true
            }
            R.id.action_print -> {
                printCurrentPage()
                true
            }
            R.id.action_logout -> {
                loadRoute("/auth/logout")
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    override fun onResume() {
        super.onResume()
        // If URL settings changed in native settings, refresh route.
        if (webView.url.isNullOrBlank()) {
            loadRoute("/auth/login")
        }
    }

    private fun configureWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.allowFileAccess = true
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: android.webkit.WebResourceRequest?,
            ): Boolean {
                return false
            }
        }

        webView.setDownloadListener { url, userAgent, contentDisposition, mimetype, _ ->
            val request = DownloadManager.Request(url.toUri())
            request.setMimeType(mimetype)
            request.addRequestHeader("User-Agent", userAgent)
            request.setDescription(getString(R.string.download_description))
            val guessedName = URLUtil.guessFileName(url, contentDisposition, mimetype)
            request.setTitle(guessedName)
            request.setNotificationVisibility(
                DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED,
            )
            request.setDestinationInExternalPublicDir(
                Environment.DIRECTORY_DOWNLOADS,
                guessedName,
            )
            val manager = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            manager.enqueue(request)
        }
    }

    private fun configureQuickActions() {
        findViewById<Button>(R.id.btnDashboard).setOnClickListener { loadRoute("/dashboard") }
        findViewById<Button>(R.id.btnProducts).setOnClickListener { loadRoute("/products") }
        findViewById<Button>(R.id.btnCustomers).setOnClickListener { loadRoute("/customers") }
        findViewById<Button>(R.id.btnCategories).setOnClickListener { loadRoute("/categories") }
        findViewById<Button>(R.id.btnBilling).setOnClickListener { loadRoute("/billing/new") }
        findViewById<Button>(R.id.btnInvoices).setOnClickListener { loadRoute("/invoices") }
        findViewById<Button>(R.id.btnSettings).setOnClickListener { loadRoute("/settings") }
    }

    private fun configureBackHandler() {
        onBackPressedDispatcher.addCallback(this) {
            if (webView.canGoBack()) {
                webView.goBack()
            } else {
                finish()
            }
        }
    }

    private fun loadRoute(route: String) {
        val rootUrl = getConfiguredBaseUrl()
        val normalizedRoute = if (route.startsWith("/")) route else "/$route"
        webView.loadUrl("$rootUrl$normalizedRoute")
    }

    private fun getConfiguredBaseUrl(): String {
        val preferences = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val configured = preferences.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        return configured.trim().trimEnd('/')
    }

    private fun printCurrentPage() {
        val printManager = getSystemService(Context.PRINT_SERVICE) as PrintManager
        val adapter = webView.createPrintDocumentAdapter("inventory-receipt")
        val attributes = PrintAttributes.Builder()
            .setMediaSize(PrintAttributes.MediaSize.UNKNOWN_PORTRAIT)
            .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
            .build()
        printManager.print(getString(R.string.print_job_name), adapter, attributes)
    }

    companion object {
        const val PREFS_NAME = "inventory_mobile_prefs"
        const val KEY_BASE_URL = "base_url"
        const val DEFAULT_BASE_URL = "http://10.0.2.2:5000"
    }
}
